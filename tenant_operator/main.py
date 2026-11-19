"""The Tenant operator: watches Tenant objects and builds each tenant."""

import kopf
from kubernetes import config, dynamic
from kubernetes.client import api_client
from kubernetes.dynamic.exceptions import NotFoundError

from tenant_operator.resources import GROUP, MANAGED_BY, VERSION, build_all

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


@kopf.on.create(GROUP, VERSION, "tenants")
def on_create(name, uid, spec, logger, **_):
    reconcile(name, uid, spec, logger)


@kopf.on.update(GROUP, VERSION, "tenants", field="spec")
def on_update(name, uid, spec, logger, **_):
    reconcile(name, uid, spec, logger)


@kopf.on.resume(GROUP, VERSION, "tenants")
def on_resume(name, uid, spec, logger, **_):
    reconcile(name, uid, spec, logger)


@kopf.timer(GROUP, VERSION, "tenants", interval=30, initial_delay=30)
def on_timer(name, uid, spec, logger, **_):
    reconcile(name, uid, spec, logger)


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