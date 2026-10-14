#!/bin/bash
# Install Chat Agent as a macOS LaunchAgent
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_TEMPLATE="$REPO_DIR/com.example.chat-agent.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.example.chat-agent.plist"
LABEL="com.example.chat-agent"

# Unload if already loaded
if launchctl list "$LABEL" &>/dev/null; then
    echo "Unloading existing agent..."
    launchctl unload "$PLIST_DST" 2>/dev/null || true
fi

# Render plist from template, substituting paths
echo "Installing plist to $PLIST_DST"
sed -e "s|__REPO_DIR__|$REPO_DIR|g" \
    -e "s|__HOME__|$HOME|g" \
    "$PLIST_TEMPLATE" > "$PLIST_DST"

# Create log directory
mkdir -p "$HOME/Library/Logs"

# Load
echo "Loading LaunchAgent..."
launchctl load "$PLIST_DST"

echo "Chat Agent installed and running."
echo "Logs: tail -f ~/Library/Logs/chat-agent.log"
