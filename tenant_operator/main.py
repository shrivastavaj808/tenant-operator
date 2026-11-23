"""The Tenant operator: watches Tenant objects and builds each tenant."""

from datetime import datetime, timezone

import kopf
from kubernetes import config, dynamic
from kubernetes.client import api_client
from kubernetes.dynamic.exceptions import NotFoundError, DynamicApiError

from tenant_operator.resources import GROUP, MANAGED_BY, VERSION, build_all, namespace_name

FIELD_MANAGER = "tenant-operator"
client = None   


@kopf.on.startup()
def connect(logger, **_):
    global client
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    client = dynamic.DynamicClient(api_client.ApiClient())
    logger.info("Connected to Kubernetes cluster")

def apply(obj):
    api = client.resources.get(api_version=obj["apiVersion"], kind=obj["kind"])
    client.server_side_apply(
        api,
        body=obj,
        namespace=obj.get("metadata", {}).get("namespace"),
        field_manager=FIELD_MANAGER,
        force_conflicts=True
    )

def reconcile(name, uid, spec, logger):
    objects = build_all(name, uid, spec)
    for obj in objects:
        apply(obj)
    logger.info(f"Tenant {name} reconciled: {len(objects)} objects applied")

def deployment_replicas(name, spec):
    deployments = client.resources.get(api_version="apps/v1", kind="Deployment")
    dep = deployments.get(name="tenant-app", namespace=namespace_name(name))
    ready = dep.status.readyReplicas or 0
    desired = spec.get("replicas", 1)
    return ready, desired

def ready_condition(old_status, ok, reason, message):
    new = "True" if ok else "False"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    old = next(
        (c for c in old_status.get("conditions", []) 
         if c.get("type") == "Ready"), 
         None,
        )
    since = old["lastTransitionTime"] if old and old.get("status") == new else now
    return {
        "type": "Ready",
        "status": new,
        "lastTransitionTime": since,
        "reason": reason,
        "message": message,
    }

def reconcile_and_report(name, uid, spec, meta, status, patch, logger):
    try:
        reconcile(name, uid, spec, logger)
    except DynamicApiError as e:
        logger.error(f"Applying tenant {name} failed: {e.reason}")
        cond = ready_condition(status, False, "ApplyFailed", str(e.reason))
    else:
        ready, desired = deployment_replicas(name, spec)
        if ready >= desired:
            cond = ready_condition(status, True, " AllReplicasReady", f"{ready}/{desired} replicas ready")
        else:
            cond = ready_condition(status, False, "ReplicasNotReady", f"{ready}/{desired} replicas ready")
    patch.status["conditions"] = [cond]
    patch.status["observedGeneration"] = meta.get("generation")


@kopf.on.create(GROUP, VERSION, "tenants")
def on_create(name, uid, spec, meta, status, patch, logger, **_):
    reconcile_and_report(name, uid, spec, meta, status, patch, logger)


@kopf.on.update(GROUP, VERSION, "tenants", field="spec")
def on_update(name, uid, spec, meta, status, patch, logger, **_):
    reconcile_and_report(name, uid, spec, meta, status, patch, logger)


@kopf.on.resume(GROUP, VERSION, "tenants")
def on_resume(name, uid, spec, meta, status, patch, logger, **_):
    reconcile_and_report(name, uid, spec, meta, status, patch, logger)


@kopf.timer(GROUP, VERSION, "tenants", interval=30, initial_delay=30)
def on_timer(name, uid, spec, meta, status, patch, logger, **_):
    reconcile_and_report(name, uid, spec, meta, status, patch, logger)


@kopf.on.event(
    "networking.k8s.io", "v1", "networkpolicies",
    labels={"app.kubernetes.io/managed-by": MANAGED_BY},
)

def on_policy_event(event, logger, **_):
    if event["type"] != "DELETED":
        return
    policy = event["object"]
    tenant = policy["metadata"]["labels"]["tenant"]
    tenants = client.resources.get(api_version=f"{GROUP}/{VERSION}", kind="Tenant")
    try:
        obj = tenants.get(name=tenant)
    except NotFoundError:
        return
    if obj.metadata.deletionTimestamp:
        return
    logger.warning(f"NetworkPolicy {policy['metadata']['name']} was deleted, restoring tenant {tenant}")
    reconcile(tenant, obj.metadata.uid, obj.to_dict()["spec"], logger)  