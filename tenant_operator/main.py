"""The Tenant operator: watches Tenant objects and builds each tenant."""

import kopf
from kubernetes import config, dynamic
from kubernetes.client import api_client

from tenant_operator.resources import GROUP, VERSION, build_all

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
