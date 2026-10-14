# chat-agent

A background service that bridges Google Chat to a local AI CLI, so you can run AI commands from your phone without opening a terminal.

## Problem

A local AI coding/agent CLI is powerful but tied to your desk -- you need a terminal and your machine in front of you. There was no way to trigger it from a phone or anywhere else without a terminal session.

## What it does

Polls a private Google Chat space for new messages, pipes each one into a local AI CLI, and posts the response back to the same chat thread. Runs as a persistent background daemon (launchd on macOS).

- Any message in the space becomes a CLI prompt
- Full tool/skill access the CLI already has, available remotely
- Responses posted back to the same Chat thread
- Auto-restarts on failure via launchd `KeepAlive`

## How it works (agent flow)

```
Phone (Google Chat)
    |
    v
Private Google Chat space  <-- you type here
    ^  |
    |  v  (polls every N seconds)
Background script (LaunchAgent)
    |
    v
local AI CLI --print        <-- runs your prompt
    |
    v
Response sent back to Chat  <-- you read here
```

A Python script runs as a macOS LaunchAgent. On a configurable interval it checks a private Google Chat space for new messages, pipes each one to the local AI CLI in print mode, and sends the response back as a thread reply. All connections are outbound from your machine -- no ports opened, no webhooks.

## Guardrails

- **Loop prevention:** the agent tracks the message IDs it sends itself and skips them on the next poll, so it never responds to its own output.
- **Stateless:** each message is an independent call with no conversation memory carried between messages.
- **Crash-safe resume:** the last processed timestamp is persisted after every message, so a crash mid-poll doesn't cause duplicate reprocessing or lost messages.
- **Message size cap:** Google Chat caps messages at 4096 characters; longer responses are truncated with a visible marker rather than silently failing to send.
- **Budget cap:** a `max_budget_usd` config value is passed to the AI CLI per prompt to bound spend on any single request.

## Data sources

- Google Chat (poll for messages, send replies) via a generic Google Workspace CLI wrapper exposing `chat messages list` / `chat messages send`.
- A local AI CLI binary, invoked as a subprocess per message.

## Configure

Nothing identifying is hardcoded -- it all comes from a local config file and the LaunchAgent plist template.

### 1. Create a private Google Chat space

Using whatever Google Workspace CLI/wrapper you have, create a private space and note its resource name (e.g. `spaces/XXXXXXXXXXX`).

### 2. Create the config file

```bash
cat > ~/.config/chat-agent.json << 'EOF'
{
  "space_id": "spaces/YOUR_SPACE_ID",
  "poll_interval_seconds": 10,
  "model": "sonnet",
  "max_budget_usd": 5,
  "self_user_id": "users/YOUR_USER_ID",
  "workspace_cli_bin": "/path/to/workspace-cli",
  "ai_cli_bin": "/path/to/ai-cli"
}
EOF
```

| Field | Description |
|-------|-------------|
| `space_id` | Google Chat space to monitor |
| `poll_interval_seconds` | How often to check for new messages |
| `model` | Model name to pass to the AI CLI |
| `max_budget_usd` | Max spend per single prompt |
| `workspace_cli_bin` | Full path to your Google Workspace CLI binary |
| `ai_cli_bin` | Full path to your local AI CLI binary |

### 3. Install

```bash
bash install.sh
```

This renders `com.example.chat-agent.plist` with your actual paths, copies it to `~/Library/LaunchAgents/`, and loads it. The agent starts immediately and auto-starts on login.

### 4. Test

Send a message in the Google Chat space from your phone. You should see:
1. A "Thinking..." reply within a few seconds
2. The full response shortly after

## Managing

```bash
# Check if running
launchctl list com.example.chat-agent

# View logs
tail -f ~/Library/Logs/chat-agent.log

# Stop
launchctl unload ~/Library/LaunchAgents/com.example.chat-agent.plist

# Start
launchctl load ~/Library/LaunchAgents/com.example.chat-agent.plist

# Reinstall after editing agent.py
bash install.sh
```

## Files

| File | Purpose |
|------|---------|
| `agent.py` | Main polling script |
| `com.example.chat-agent.plist` | LaunchAgent template (paths substituted at install time) |
| `install.sh` | Render the plist and install/reload the LaunchAgent |
| `uninstall.sh` | Stop and remove the LaunchAgent |
| `~/.config/chat-agent.json` | Runtime config |
| `~/.config/chat-agent-lastpoll` | Last processed timestamp |
| `~/.config/chat-agent-sent-ids.json` | Bot message IDs (loop prevention) |
| `~/Library/Logs/chat-agent.log` | Logs |

## Notes

- The agent only runs while your machine is on and not sleeping.
- No conversation memory is kept between messages -- each prompt is handled independently.
