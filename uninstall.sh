#!/bin/bash
# Uninstall Chat Agent LaunchAgent
set -e

PLIST_DST="$HOME/Library/LaunchAgents/com.example.chat-agent.plist"
LABEL="com.example.chat-agent"

if launchctl list "$LABEL" &>/dev/null; then
    echo "Unloading agent..."
    launchctl unload "$PLIST_DST"
else
    echo "Agent not currently loaded."
fi

if [ -f "$PLIST_DST" ]; then
    echo "Removing plist..."
    rm "$PLIST_DST"
fi

echo "Chat Agent uninstalled."
echo "Config preserved at ~/.config/chat-agent.json"
echo "Logs preserved at ~/Library/Logs/chat-agent.log"
