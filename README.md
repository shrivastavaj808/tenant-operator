# Tenant Operator

A Kubernetes operator, written in Python with [kopf](https://kopf.readthedocs.io/), that automates onboarding tenants onto a multi-tenant SaaS platform.

> 🚧 Work in progress, built step by step as a learning and portfolio project.

## The idea

Creating one `Tenant` resource tells the operator to build and maintain everything that tenant needs:

| Piece | Kubernetes object | Why |
|---|---|---|
| Their own space | Namespace | Isolation between customers |
| Who can do what | Role + RoleBinding | Least-privilege access |
| Walls between tenants | NetworkPolicy | Tenants can't reach each other |
| Fair resource use | ResourceQuota | One tenant can't starve others |
| Their app | Deployment + Service + Ingress | The actual product |

If someone changes or deletes any of these by hand, the operator puts them back. When the tenant is deleted, everything is cleaned up.

## Roadmap

- [x] Phase 0: Project setup
- [x] Phase 1: Tenant web app + secure container image
- [ ] Phase 2: One tenant set up by hand
- [ ] Phase 3: `Tenant` CRD with validation
- [ ] Phase 4: Operator handlers + drift correction
- [ ] Phase 5: Status conditions, events, finalizers
- [ ] Phase 6: Tests + CI pipeline
- [ ] Phase 7: Helm chart, least-privilege RBAC, Argo CD
- [ ] Phase 8: Terraform, metrics, troubleshooting runbook