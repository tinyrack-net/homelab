# Cilium host firewall rollout

This policy is active. Any rollout or policy change must start only after
out-of-band NanoKVM access has been verified and the host endpoint is in policy
audit mode.

1. Confirm `Host firewall: Enabled` in `cilium-dbg status`.
2. Find the endpoint with identity `reserved:host` and enable audit mode:

   ```sh
   kubectl --context homelab -n kube-system exec ds/cilium -- sh -c \
     'cilium-dbg endpoint config $(cilium-dbg endpoint get -l reserved:host -o jsonpath="{$[0].id}") PolicyAuditMode=Enabled'
   ```

3. Uncomment `cilium-host-firewall.yaml` in the production infrastructure
   overlay and reconcile through Flux.
4. The standard rollout observes audit verdicts for at least 24 hours. An
   explicitly approved accelerated rollout may use a 10-minute full service
   smoke-test window when out-of-band recovery is confirmed. If Cilium restarts
   during the audit, re-enable audit mode and restart the observation window.
5. When all required flows match an allow rule, disable audit mode to enforce.

Emergency recovery uses the same `PolicyAuditMode=Enabled` command from
NanoKVM or a local `crictl exec` session.
