#!/usr/bin/env bash
set -euo pipefail
unit_path="$HOME/.config/systemd/user/tcf-importer.service"
if [[ -e "$unit_path" ]]; then
    systemctl --user disable --now tcf-importer.service
    rm -- "$unit_path"
    systemctl --user daemon-reload
fi
printf '%s\n' 'Service removed. Notes, configuration, logs, receipts, and virtualenv preserved.'
