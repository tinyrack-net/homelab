# AGENTS.md

## Repo Shape
- This is a Flux GitOps repo for a single `production` cluster, not a conventional app repo.
- Flux watches `./clusters/production` via `clusters/production/flux-system/gotk-sync.yaml`.
- `clusters/production/infrastructure.yaml` syncs `./infrastructure/overlays/production`; `clusters/production/apps.yaml` syncs `./apps/overlays/production` and explicitly `dependsOn: infrastructure`.
- `apps/overlays/production/kustomization.yaml` and `infrastructure/overlays/production/kustomization.yaml` are the enable/disable lists. Comment or uncomment entries there to turn workloads on or off.
- `apps/base/*` and `infrastructure/base/*` contain the real manifests. Most overlay files are Flux `Kustomization` CRs that point at those base directories.

## Verify Changes
- Do not use `kubectl kustomize ./clusters/production`; that directory is not a kustomize root.
- Verify the Flux layer with `kubectl kustomize ./apps/overlays/production` and `kubectl kustomize ./infrastructure/overlays/production`.
- Verify the actual workload you changed with `kubectl kustomize ./apps/base/<name>` or `kubectl kustomize ./infrastructure/base/<name>`.
- Repository dependencies matter: many app bases depend on `load-repositories`, and many infrastructure bases depend on `infrastructure-repositories`.
- `infrastructure/base/cloudnative-pg/kustomization.yaml` pulls a remote release URL, so building that base needs network access.

## Secrets
- Committed `*.secret.yaml` and `*.secrets.yaml` files are encrypted `SealedSecret` manifests, often stored as JSON rather than YAML.
- Do not replace them with plaintext `Secret` resources.
- Recreate encrypted secrets with the repo certificate using the same pattern as `README.md`: `kubectl create secret generic <secret-name> --namespace <namespace> --dry-run=client --from-literal=KEY=VALUE -o yaml | kubeseal --cert ./tinyrack-homelab-secret-key.crt > ./<name>.secret.yaml`.
- The public cert is committed at `./tinyrack-homelab-secret-key.crt`; the private key file `tinyrack-homelab-secret-key.key` is intentionally gitignored.

## Bootstrap / Ops
- The README bootstrap flow is: install K3S without Traefik, restore the Sealed Secrets TLS secret, then run `flux bootstrap github --repository=homelab --branch=main --path=./clusters/production --owner=tinyrack-net`.

## Known Gotcha
- `flux build kustomization apps --path .` is currently not a reliable whole-repo verification step: `apps/base/ghost-tinyrack/ghost.ingress-route.yaml` defines `Middleware redirect-to-https` in namespace `ghost-system`, which collides with `apps/base/ghost` when both are built together. Prefer verifying the specific base you changed unless you are fixing that collision.
