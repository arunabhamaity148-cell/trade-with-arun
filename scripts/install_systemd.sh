#!/usr/bin/env bash
# Install/refresh the systemd unit file for twa.
set -eu
DEST="${1:-/etc/systemd/system/twa.service}"
TWA_HOME="${TWA_HOME:-/opt/trade_with_arun}"
USER_NAME="${USER_NAME:-twa}"
cat > "$DEST" <<EOF
[Unit]
Description=TRADE WITH ARUN signal engine
After=network-online.target

[Service]
Type=simple
User=${USER_NAME}
WorkingDirectory=${TWA_HOME}
EnvironmentFile=${TWA_HOME}/.env
ExecStart=${TWA_HOME}/.venv/bin/twa run
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
echo "Wrote $DEST"
