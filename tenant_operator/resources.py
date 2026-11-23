"""Build the Kubernetes objects that make up one tenant.

Every function here is pure: it takes the tenant's name, uid and spec and
returns plain Python dicts. Nothing here talks to the cluster.
"""

GROUP = "platform.example.com"
VERSION = "v1alpha1"
MANAGED_BY = "tenant-operator"
APP_IMAGE = "tenant-app:0.1.1"
APP_PORT = 8080

PLANS = {
    "small": {
        "pods": "5",
        "requests.cpu": "500m",
        "requests.memory": "256Mi",
        "limits.memory": "512Mi",       
    },
    "large": {
        "pods": "10",
        "requests.cpu": "1",
        "requests.memory": "512Mi",
        "limits.memory": "1Gi",
    },
}

PRIORITY = {
        "small": "tenant-standard",
        "large": "tenant-premium",
    }

def namespace_name(tenant):
    return f"tenant-{tenant}"


def metadata(name, tenant, uid, namespace=None):
    meta = {
        "name": name,
        "labels": {
            "tenant": tenant,
            "app.kubernetes.io/managed-by": MANAGED_BY,
        },
        "ownerReferences": [
            {
                "apiVersion": f"{GROUP}/{VERSION}",
                "kind": "Tenant",
                "name": tenant,
                "uid": uid,
                "controller": True,
                "blockOwnerDeletion": True,
            }
        ],
    }
    if namespace:
        meta["namespace"] = namespace
    return meta


def build_namespace(tenant, uid):
    meta = metadata(namespace_name(tenant), tenant, uid)
    meta["labels"]["pod-security.kubernetes.io/enforce"] = "restricted"
    meta["labels"]["pod-security.kubernetes.io/enforce-version"] = "latest"
    return {
        "apiVersion": "v1",
        "kind": "Namespace",
        "metadata": meta,
    }   


def build_quota(tenant, uid, plan):
    return {
        "apiVersion": "v1",
        "kind": "ResourceQuota",
        "metadata": metadata("tenant-quota", tenant, uid, namespace_name(tenant)),
        "spec": {
            "hard": PLANS[plan]
        },
    }


def build_role(tenant, uid):
    return {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "Role",
        "metadata": metadata("tenant-developer", tenant, uid, namespace_name(tenant)),
        "rules": [
            {
                "apiGroups": [""],
                "resources": ["pods", "pods/log", "services", "configmaps"],
                "verbs": ["get", "list", "watch"],
            },
            {
                "apiGroups": ["apps"],
                "resources": ["deployments"],
                "verbs": ["get", "list", "watch", "update", "patch"],
            },
        ],
    }


def build_role_binding(tenant, uid):
    return {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "RoleBinding",
        "metadata": metadata("tenant-developers", tenant, uid, namespace_name(tenant)),
        "subjects": [
            {
                "kind": "Group",
                "name": f"{tenant}-developers",
                "apiGroup": "rbac.authorization.k8s.io",
            }
        ],
        "roleRef": {
            "kind": "Role",
            "name": "tenant-developer",
            "apiGroup": "rbac.authorization.k8s.io",
        },
    }


def build_configmap(tenant, uid):
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": metadata("tenant-config", tenant, uid, namespace_name(tenant)),
        "data": {
            "TENANT_NAME": tenant,
        },
    }


def build_deployment(tenant, uid, spec):
    pod_labels = {"app": "tenant-app", "tenant": tenant}
    meta = metadata("tenant-app", tenant, uid, namespace_name(tenant))
    meta["labels"]["app"] = "tenant-app"
    probe = {
        "httpGet": {
            "path": "/healthz",
            "port": "http",
        }
    }
    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": meta,
        "spec": {
            "selector": {"matchLabels": {"app": "tenant-app"}},
            "strategy": {"type": "RollingUpdate",
                         "rollingUpdate": {"maxUnavailable": 1, "maxSurge": 1},
            },
            "template": {
                "metadata": {"labels": pod_labels},
                "spec": {
                    "securityContext": {
                        "runAsNonRoot": True,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "priorityClassName" : PRIORITY[spec["plan"]],
                    "initContainers" : [
                        {
                            "name" : "preflight",
                            "image" : APP_IMAGE,
                            "command" : [
                                "python", "-c",
                                "import os, sys; n = os.environ.get('TENANT_NAME'); "
                                "print(f'preflight: TENANT_NAME={n}'); sys.exit(0 if n else 1)",
                            ],
                            "envFrom" : [{"configMapRef": {"name": "tenant-config"}}],
                            "resources" : {
                                "requests" : {"cpu": "10m", "memory": "32Mi"},
                                "limits" : {"memory": "64Mi"},
                            },
                            "securityContext" : {
                                "allowPrivilegeEscalation": False,
                                "capabilities": {"drop": ["ALL"]},
                            },
                        }
                    ],
                    "containers": [
                        {
                            "name": "app",
                            "image": APP_IMAGE,
                            "imagePullPolicy": "IfNotPresent",
                            "ports": [{"name": "http", "containerPort": APP_PORT}],
                            "envFrom": [
                                {"configMapRef": {"name": "tenant-config"}},
                            ],
                            "volumeMounts": [
                                {"name": "secrets", "mountPath": "/etc/tenant-secrets", "readOnly": True},
                            ],
                            "resources": {
                                "requests": {"cpu": "50m", "memory": "64Mi"},
                                "limits": {"memory": "128Mi"},
                            },
                            "readinessProbe": {**probe, "periodSeconds": 5},
                            "livenessProbe": {**probe, "initialDelaySeconds": 10, "periodSeconds": 5},
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "capabilities": {"drop": ["ALL"]},
                            },
                        }
                    ],
                    "volumes": [
                        {"name": "secrets", "secret": {"secretName": "tenant-secrets", "optional": True}},
                    ],
                },
            },
        },
    }
    if spec["plan"] != "large":
        deployment["spec"]["replicas"] = spec["replicas"]
    return deployment 

def build_service(tenant, uid):
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": metadata("tenant-app", tenant, uid, namespace_name(tenant)),
        "spec": {
            "selector": {"app": "tenant-app"},
            "ports": [{"name": "http", "port": 80, "targetPort": "http"}],
        },
    }


def build_network_policy(tenant, uid):
    ns = namespace_name(tenant)

    def policy(name, spec):
        return {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": metadata(name, tenant, uid, ns),
            "spec": {"policyTypes": ["Ingress"], **spec},
        }
    
    return [
        policy("default-deny-ingress", {"podSelector": {}}),
        policy(
            "allow-same-namespace",
            {"podSelector": {}, "ingress": [{"from": [{"podSelector": {}}]}]},
        ),
        policy(
            "allow-ingress-controller",
            {
                "podSelector": {"matchLabels": {"app": "tenant-app"}},
                "ingress": [
                    {
                        "from": [
                            {
                                "namespaceSelector": {
                                    "matchLabels": {
                                        "kubernetes.io/metadata.name": "traefik"
                                    }
                                }
                            }
                        ],
                        "ports": [{"port": APP_PORT}],
                    }
                ],
            },
        ),
    ]


def build_ingress(tenant, uid):
    host = f"{tenant}.tenants.local"
    meta = metadata("tenant-app", tenant, uid, namespace_name(tenant))
    meta["annotations"] = {
        "cert-manager.io/cluster-issuer": "tenants-ca",
    }
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "Ingress",
        "metadata": meta,
        "spec": {
            "ingressClassName": "traefik",
            "tls": [{"hosts": [host], "secretName": "tenant-app-tls"}],
            "rules": [
                {
                    "host": host,
                    "http": {
                        "paths": [
                            {
                                "path": "/",
                                "pathType": "Prefix",
                                "backend": {
                                    "service": {"name": "tenant-app", "port": {"name": "http"}}
                                },
                            }
                        ]
                    },
                }
            ],
        },
    }


def build_hpa(tenant, uid, min_replicas):
    return {
        "apiVersion": "autoscaling/v2",
        "kind": "HorizontalPodAutoscaler",
        "metadata": metadata("tenant-app", tenant, uid, namespace_name(tenant)),
        "spec": {
            "scaleTargetRef": {"apiVersion": "apps/v1", "kind": "Deployment", "name": "tenant-app"},
            "minReplicas": min_replicas,
            "maxReplicas": 4,
            "metrics": [
                {
                    "type": "Resource",
                    "resource": {"name": "cpu", "target": {"type": "Utilization", "averageUtilization": 70}},
                }
            ],
        },
    }


def build_all(tenant, uid, spec):
    objects = [
        build_namespace(tenant, uid),
        build_quota(tenant, uid, spec["plan"]),
        build_role(tenant, uid),
        build_role_binding(tenant, uid),
        build_configmap(tenant, uid),
        build_deployment(tenant, uid, spec),
        build_service(tenant, uid),
        *build_network_policy(tenant, uid),
        build_ingress(tenant, uid), 
    ]
    if spec["plan"] == "large":
        objects.append(build_hpa(tenant, uid, spec["replicas"]))
    return objects
    