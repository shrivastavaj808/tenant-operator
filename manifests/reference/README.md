# Reference only: do not apply

These are the Kustomize manifests from Phase 2–3, before the operator existed.
They are kept for learning. The operator (`tenant_operator/resources.py`) now
builds every tenant object.

⚠️ Never run `kubectl apply -k` on these: it would fight the operator's
server-side apply. To study them safely, render without applying:

    kubectl kustomize manifests/reference/kustomize-tenants/overlays/acme
