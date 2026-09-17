# Issuary login operations

Home Assistant stores HACS, custom integrations, UI configuration and users on
the `/config` PVC. Git manages the Issuary client and network policies. Install
and update OpenID Connect through HACS; do not add an init container.

## Complete setup

1. Sign in as the existing Home Assistant owner. Add the HACS integration and
   complete its GitHub device authorization using your own account.
2. In HACS, install `christiaangoossens/hass-oidc-auth` version `v1.2.1`, then
   restart Home Assistant. Use manual updates.
3. Add **OpenID Connect/SSO Authentication**, selecting a generic/custom provider.
   Use client ID `home-assistant`, no client secret, and discovery URL
   `https://auth.winetree94.com/.well-known/openid-configuration`.
   Disable groups and automatic user linking. Keep PKCE and TLS verification
   enabled. The registered callback is
   `https://home-assistant.winetree94.com/auth/oidc/callback`.
4. Keep the owner session open. In a separate browser session, sign in with
   Issuary to create a new Home Assistant user. It starts as a **regular user**.
   In the owner session, promote that specific new user to administrator.
5. Verify administrator access after signing out and back in, and verify the
   Companion App device-code login. Confirm the callback uses HTTPS. If it
   does not, fix reverse-proxy handling before proceeding; do not register an
   HTTP callback or disable TLS verification.
6. Only after these checks, merge the following into the existing
   `/config/configuration.yaml` (one `homeassistant` key), then restart:

   ```yaml
   homeassistant:
     auth_providers: []
   ```

Keep the original owner account. New OIDC accounts are separate identities;
existing person/device associations do not migrate automatically. Disabling
local login does not revoke existing sessions or API tokens. Owner-only actions
require temporarily restoring local authentication.

## Backup and recovery

The pre-HACS configuration archive is on the PVC at
`/config/.backups/pre-hacs-20260917T130024Z.tar.gz` (directory mode 0700,
archive mode 0600). It includes credentials and must never be committed or
served over HTTP. This is a live configuration rollback archive, not an
independent disaster-recovery backup or a guaranteed consistent SQLite backup.

If Issuary or the OIDC integration is unavailable, use administrative access
with `kubectl --context homelab` to edit the PVC's configuration and restore:

```yaml
homeassistant:
  auth_providers:
    - type: homeassistant
```

Restart the Home Assistant Deployment in `home-assistant-system`. Use the
original local owner account; with automatic OIDC redirection enabled, open
`https://home-assistant.winetree94.com/?skip_oidc_redirect=true`.
Restore only the required configuration file from the archive, preserving
newer `.storage` users, tokens, integrations and device state. If Home Assistant
cannot stay running, stop its Deployment and mount `home-assistant-data` in a
temporary maintenance Pod to repair the file; do not mount the PVC concurrently
with another Home Assistant instance.

For network verification, request the Discovery document and its `jwks_uri`
from inside the Home Assistant Pod with TLS verification enabled. The path is
Home Assistant → external Traefik (TCP 8443) → Issuary (TCP 8080). Keep both
sides of the Cilium policy in the application's manifests.
