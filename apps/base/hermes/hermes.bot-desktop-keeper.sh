#!/command/with-contenv sh
# shellcheck shell=sh
# Keeps the default profile's Bot Desktop running at all times.
#
# Hermes starts the screen only on demand and does not bring it back after a
# pod restart. This s6 legacy service (/etc/services.d/bot-desktop) starts it
# at boot and re-checks every minute, restarting it if Xvnc/Xfce died.
# `screen start` is idempotent: it returns at once when the screen is up.
# Together with bot_desktop.idle_stop_minutes: 0 the screen never stops.

# with-contenv resets HOME to /root; Hermes state lives under /opt/data.
export HOME=/opt/data
cd /opt/data || exit 1

# Give the gateway a head start on first boot (config migrations, skills sync).
sleep 20

while :; do
  if ! s6-setuidgid hermes hermes computer-use screen status 2>/dev/null | grep -q "running on DISPLAY"; then
    echo "[bot-desktop] screen not running; starting it"
    s6-setuidgid hermes hermes computer-use screen start || echo "[bot-desktop] start failed; retrying in 60s"
  fi
  sleep 60
done
