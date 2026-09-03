# Cilium host firewall rollout

This policy must not be enabled until out-of-band NanoKVM access has been
verified and the host endpoint is in policy audit mode.

1. Confirm `Host firewall: Enabled` in `cilium-dbg status`.
2. Find the endpoint with identity `reserved:host` and enable audit mode:

   ```sh
   kubectl --context homelab -n kube-system exec ds/cilium -- sh -c \
     'cilium-dbg endpoint config $(cilium-dbg endpoint get -l reserved:host -o jsonpath="{$[0].id}") PolicyAuditMode=Enabled'
   ```

3. Uncomment `cilium-host-firewall.yaml` in the production infrastructure
   overlay and reconcile through Flux.
4. Observe audit verdicts for at least 24 hours. If Cilium restarts during the
   audit, re-enable audit mode before continuing.
5. When all required flows match an allow rule, disable audit mode to enforce.

Emergency recovery uses the same `PolicyAuditMode=Enabled` command from
NanoKVM or a local `crictl exec` session.
