# Network policy rollout

Application and platform policies use the namespace label
`networking.tinyrack.net/isolation=enabled` as their enforcement switch. Policy
objects can be reconciled safely before the corresponding namespace wave is
enabled.

## Application waves

Only `network-policy-wave-1.yaml` is enabled by default. Enable the next entry
in `apps/overlays/production/kustomization.yaml` only after all workloads in the
current wave are Ready and Hubble shows no unexplained policy drops.

1. Wave 1: Beszel and Proxer
2. Wave 2: SearXNG and Karakeep
3. Wave 3: Open WebUI, LiteLLM, Guacamole, n8n, Infisical, and Issuary
4. Wave 4: DaVinci Resolve PostgreSQL, wg-easy, and RustDesk

Wave Kustomizations deliberately use `prune: false` so they can never delete an
application namespace. To roll back, first change each affected isolation label
from `enabled` to `disabled` in the wave's `namespaces.yaml` and wait for Flux to
reconcile. Only then comment out that wave and every later wave.

## Platform waves

The platform policy objects are enabled but inert. After every application wave
is healthy, enable platform namespace waves in this order:

1. Traefik, external Traefik, and cloudflared
2. CNPG, Redis operator, cert-manager, Kyverno, Flux, and Tailscale
3. Longhorn

Inspect drops during each wave with Hubble before enabling the next wave. Direct
Tailscale access to application Pod and Service CIDRs is intentionally denied;
use the internal Traefik routes instead.

The Multus `net1` interface used by wg-easy is not governed by these Cilium
policies. WireGuard peer permissions and routing rules remain a separate
security boundary.
