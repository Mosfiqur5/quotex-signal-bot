#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    printf 'Error: run this installer as root (sudo bash install.sh).\n' >&2
    exit 1
fi

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NO_SYSTEMD=0

while (($#)); do
    case "$1" in
        --no-systemd)
            NO_SYSTEMD=1
            ;;
        *)
            printf 'Unknown option: %s\nUsage: sudo bash install.sh [--no-systemd]\n' "$1" >&2
            exit 2
            ;;
    esac
    shift
done

apt-get update && apt-get install -y python3 python3-venv python3-pip git
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

if [[ ! -f "$APP_DIR/.env" ]]; then
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"

    if [[ -n "${TELEGRAM_BOT_TOKEN:-}" ]]; then
        telegram_token="$TELEGRAM_BOT_TOKEN"
    elif [[ -t 0 ]]; then
        printf 'Telegram bot token: '
        IFS= read -rs telegram_token
        printf '\n'
    else
        printf 'Error: set TELEGRAM_BOT_TOKEN or run this installer in an interactive console.\n' >&2
        exit 1
    fi

    if [[ -n "${TELEGRAM_CHAT_ID:-}" ]]; then
        telegram_chat_id="$TELEGRAM_CHAT_ID"
    elif [[ -t 0 ]]; then
        printf 'Telegram chat ID: '
        IFS= read -r telegram_chat_id
    else
        printf 'Error: set TELEGRAM_CHAT_ID or run this installer in an interactive console.\n' >&2
        exit 1
    fi

    if [[ -z "$telegram_token" || -z "$telegram_chat_id" ]]; then
        printf 'Error: Telegram bot token and chat ID cannot be empty.\n' >&2
        exit 1
    fi

    TELEGRAM_BOT_TOKEN_VALUE="$telegram_token" \
        TELEGRAM_CHAT_ID_VALUE="$telegram_chat_id" \
        python3 - "$APP_DIR/.env" <<'PY'
import os
from pathlib import Path
import sys

path = Path(sys.argv[1])
values = {
    "TELEGRAM_BOT_TOKEN": os.environ["TELEGRAM_BOT_TOKEN_VALUE"],
    "TELEGRAM_CHAT_ID": os.environ["TELEGRAM_CHAT_ID_VALUE"],
    "INTERVAL": "5m",
    "EXPIRY_MIN": "5",
}
lines = path.read_text(encoding="utf-8").splitlines()
found = set()
for index, line in enumerate(lines):
    if "=" not in line or line.lstrip().startswith("#"):
        continue
    key = line.split("=", 1)[0].strip()
    if key in values:
        lines[index] = f"{key}={values[key]}"
        found.add(key)
for key, value in values.items():
    if key not in found:
        lines.append(f"{key}={value}")
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
fi

chmod 600 "$APP_DIR/.env"

printf 'Testing Telegram delivery...\n'
if (
    cd "$APP_DIR"
    "$APP_DIR/venv/bin/python" -c \
        'import sys; from signalbot.config import load_config; from signalbot.notifier import Notifier; sys.exit(0 if Notifier(load_config()).send("Quotex signal bot setup test") else 1)'
); then
    printf 'Telegram test succeeded.\n'
else
    printf 'Telegram test failed; check the bot token, chat ID, and network. Installer will continue.\n'
fi

if ((NO_SYSTEMD)); then
    printf 'Install complete; systemd setup skipped (--no-systemd).\n'
elif [[ -n "${SYSTEMD_DIR:-}" ]]; then
    unit_dir="$SYSTEMD_DIR"
    mkdir -p "$unit_dir"
    cat > "$unit_dir/quotex-signal-bot.service" <<EOF
[Unit]
Description=Quotex signal-only Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python -m signalbot.main
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
    printf 'Unit file generated at %s/quotex-signal-bot.service; systemctl skipped because SYSTEMD_DIR is set.\n' "$unit_dir"
else
    unit_dir="/etc/systemd/system"
    mkdir -p "$unit_dir"
    cat > "$unit_dir/quotex-signal-bot.service" <<EOF
[Unit]
Description=Quotex signal-only Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python -m signalbot.main
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload && systemctl enable --now quotex-signal-bot
    printf 'Bot chalu hoyeche.\n'
    printf 'Logs dekhte: journalctl -u quotex-signal-bot -f\n'
    printf 'Bondho: sudo systemctl stop quotex-signal-bot\n'
    printf 'Chalu: sudo systemctl start quotex-signal-bot\n'
    printf 'Restart: sudo systemctl restart quotex-signal-bot\n'
    printf 'Settings bodlate: cd %s && nano .env, tarpor sudo systemctl restart quotex-signal-bot\n' "$APP_DIR"
    printf 'Update: cd %s && git pull && sudo systemctl restart quotex-signal-bot\n' "$APP_DIR"
fi
