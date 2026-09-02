#!/bin/bash
# Installs macOS LaunchAgents so the CBS Settlement app and the Cloudflare
# tunnel start at login and restart automatically if they crash.
#
# Run from anywhere:  bash settlement/deploy/install_launchagents.sh
# Re-run any time; it replaces the previous versions.
set -euo pipefail

SETTLEMENT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TUNNEL_NAME="${TUNNEL_NAME:-cbs-portal}"
AGENTS_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$SETTLEMENT_DIR/data/logs"
mkdir -p "$AGENTS_DIR" "$LOG_DIR"

PYTHON3="$(command -v python3)"
CLOUDFLARED="$(command -v cloudflared || true)"

if [ -z "$CLOUDFLARED" ]; then
  echo "WARNING: cloudflared not found on PATH — installing only the app agent."
  echo "         Install it (brew install cloudflared) and re-run this script."
fi

APP_PLIST="$AGENTS_DIR/com.cbs.settlement.plist"
cat > "$APP_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.cbs.settlement</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON3</string>
    <string>$SETTLEMENT_DIR/app.py</string>
  </array>
  <key>WorkingDirectory</key><string>$SETTLEMENT_DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>CBS_HTTPS</key><string>1</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOG_DIR/app.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/app.log</string>
</dict>
</plist>
EOF

launchctl unload "$APP_PLIST" 2>/dev/null || true
launchctl load "$APP_PLIST"
echo "Installed + started: com.cbs.settlement (app on http://127.0.0.1:5111)"

if [ -n "$CLOUDFLARED" ]; then
  TUNNEL_PLIST="$AGENTS_DIR/com.cbs.tunnel.plist"
  cat > "$TUNNEL_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.cbs.tunnel</string>
  <key>ProgramArguments</key>
  <array>
    <string>$CLOUDFLARED</string>
    <string>tunnel</string>
    <string>run</string>
    <string>--url</string>
    <string>http://127.0.0.1:5111</string>
    <string>$TUNNEL_NAME</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOG_DIR/tunnel.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/tunnel.log</string>
</dict>
</plist>
EOF
  launchctl unload "$TUNNEL_PLIST" 2>/dev/null || true
  launchctl load "$TUNNEL_PLIST"
  echo "Installed + started: com.cbs.tunnel (cloudflared '$TUNNEL_NAME')"
fi

echo
echo "Both services now start at login and restart if they crash."
echo "Logs: $LOG_DIR/app.log and $LOG_DIR/tunnel.log"
echo "To stop:   launchctl unload ~/Library/LaunchAgents/com.cbs.settlement.plist"
echo "           launchctl unload ~/Library/LaunchAgents/com.cbs.tunnel.plist"
echo "After a 'git pull', restart the app with:"
echo "           launchctl unload ~/Library/LaunchAgents/com.cbs.settlement.plist && launchctl load ~/Library/LaunchAgents/com.cbs.settlement.plist"
