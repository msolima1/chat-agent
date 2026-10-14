#!/usr/bin/env python3
"""Chat Agent: Polls a Google Chat space and pipes messages to a local AI CLI."""

import json
import logging
import subprocess
import sys
import time
from pathlib import Path

# --- Paths ---
CONFIG_PATH = Path.home() / ".config" / "chat-agent.json"
LASTPOLL_PATH = Path.home() / ".config" / "chat-agent-lastpoll"
SENT_IDS_PATH = Path.home() / ".config" / "chat-agent-sent-ids.json"
LOG_PATH = Path.home() / "Library" / "Logs" / "chat-agent.log"

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("chat-agent")


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def load_last_poll():
    if LASTPOLL_PATH.exists():
        return LASTPOLL_PATH.read_text().strip()
    return None


def save_last_poll(ts):
    LASTPOLL_PATH.write_text(ts)


def load_sent_ids():
    """Load set of message IDs sent by this agent."""
    if SENT_IDS_PATH.exists():
        try:
            return set(json.loads(SENT_IDS_PATH.read_text()))
        except (json.JSONDecodeError, TypeError):
            return set()
    return set()


def save_sent_ids(ids):
    """Save sent message IDs. Keep only the last 200 to prevent unbounded growth."""
    trimmed = list(ids)[-200:]
    SENT_IDS_PATH.write_text(json.dumps(trimmed))


def run_cli(args, timeout=30):
    """Run a CLI command and return (stdout, returncode, stderr)."""
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.stdout.strip(), result.returncode, result.stderr.strip()


def list_messages(config, limit=10):
    """List recent messages from the space."""
    cli = config["workspace_cli_bin"]
    space = config["space_id"]
    stdout, rc, stderr = run_cli(
        [cli, "chat", "messages", "list", space, "--limit", str(limit), "-o", "json", "--yes"],
        timeout=30,
    )
    if rc != 0:
        log.error("Failed to list messages: %s", stderr)
        return []
    if not stdout:
        return []
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        log.error("Invalid JSON from messages list: %s", stdout[:200])
        return []


def send_message(config, text, thread=None):
    """Send a message to the space, optionally as a thread reply. Returns message name or None."""
    cli = config["workspace_cli_bin"]
    space = config["space_id"]
    # Truncate to Google Chat's 4096 char limit
    if len(text) > 4000:
        text = text[:3950] + "\n\n... (truncated, response too long)"
    args = [cli, "chat", "messages", "send", space, "--text", text, "--yes", "-o", "json"]
    if thread:
        args.extend(["--thread", thread])
    stdout, rc, stderr = run_cli(args, timeout=30)
    if rc != 0:
        log.error("Failed to send message: %s", stderr)
        return None
    # Parse response to get message name for tracking
    try:
        resp = json.loads(stdout)
        return resp.get("name")
    except (json.JSONDecodeError, TypeError):
        return None


def strip_cli_banner(text, noise_lines=None):
    """Strip the AI CLI's startup banner/noise lines from output."""
    marker = "Launching AI CLI..."
    idx = text.find(marker)
    if idx != -1:
        text = text[idx + len(marker):]
    for noise in (noise_lines or [
        "Skills are managed via ~/MySkills.",
        "Warning: YOLO MODE ENABLED:",
        "Preparing runtime...",
    ]):
        lines = text.split("\n")
        lines = [l for l in lines if noise not in l]
        text = "\n".join(lines)
    return text.strip()


def run_ai_cli(config, prompt):
    """Run the local AI CLI in print mode with the given prompt and return the response."""
    ai_cli = config["ai_cli_bin"]
    model = config.get("model", "sonnet")
    budget = str(config.get("max_budget_usd", 5))
    args = [
        ai_cli, "--yolo", "claude", "--",
        "--print",
        "--model", model,
        "--max-budget-usd", budget,
        prompt,
    ]
    log.info("Running AI CLI with prompt: %s", prompt[:100])
    try:
        stdout, rc, stderr = run_cli(args, timeout=300)  # 5 min timeout
        if rc != 0:
            log.error("AI CLI failed (rc=%d): %s", rc, stderr[:500])
            return f"Error running AI CLI (exit code {rc}):\n{stderr[:500]}"
        if not stdout:
            return "(empty response from AI CLI)"
        return strip_cli_banner(stdout)
    except subprocess.TimeoutExpired:
        log.error("AI CLI timed out after 300s")
        return "Error: AI CLI timed out after 5 minutes."


def process_message(config, msg, sent_ids):
    """Process a single incoming message. Returns updated sent_ids."""
    text = msg.get("text", "").strip()
    thread = msg.get("thread", "")
    msg_name = msg.get("name", "")

    if not text:
        log.info("Skipping empty message: %s", msg_name)
        return sent_ids

    log.info("Processing message: %s", text[:100])

    # Send "Thinking..." acknowledgment in the same thread
    ack_name = send_message(config, "Thinking...", thread=thread)
    if ack_name:
        sent_ids.add(ack_name)

    # Run the AI CLI
    response = run_ai_cli(config, text)

    # Send the response back in the same thread
    resp_name = send_message(config, response, thread=thread)
    if resp_name:
        sent_ids.add(resp_name)

    save_sent_ids(sent_ids)
    log.info("Responded to message %s (%d chars)", msg_name, len(response))
    return sent_ids


def poll_loop(config):
    """Main polling loop."""
    space = config["space_id"]
    interval = config.get("poll_interval_seconds", 10)
    last_poll = load_last_poll()
    sent_ids = load_sent_ids()

    log.info("Starting poll loop for %s (interval=%ds)", space, interval)
    log.info("Tracking %d sent message IDs", len(sent_ids))
    if last_poll:
        log.info("Resuming from last poll: %s", last_poll)

    while True:
        try:
            messages = list_messages(config)
            if not messages:
                time.sleep(interval)
                continue

            # Sort chronologically (oldest first)
            messages.sort(key=lambda m: m.get("createTime", ""))

            # Filter to only new messages not sent by us
            new_messages = []
            for msg in messages:
                create_time = msg.get("createTime", "")
                msg_name = msg.get("name", "")

                # Skip messages we sent (loop prevention)
                if msg_name in sent_ids:
                    continue

                # Skip messages we've already processed (by timestamp)
                if last_poll and create_time <= last_poll:
                    continue

                new_messages.append(msg)

            if new_messages:
                log.info("Found %d new message(s) to process", len(new_messages))

            for msg in new_messages:
                sent_ids = process_message(config, msg, sent_ids)
                # Update last poll after each message so we don't re-process on crash
                last_poll = msg.get("createTime", last_poll)
                save_last_poll(last_poll)

        except KeyboardInterrupt:
            log.info("Shutting down (keyboard interrupt)")
            break
        except Exception:
            log.exception("Error in poll loop")

        time.sleep(interval)


def main():
    if not CONFIG_PATH.exists():
        log.error("Config not found at %s", CONFIG_PATH)
        sys.exit(1)

    config = load_config()
    log.info("Chat Agent starting")
    log.info("Space: %s", config["space_id"])
    log.info("Model: %s", config.get("model", "sonnet"))
    log.info("Poll interval: %ds", config.get("poll_interval_seconds", 10))

    poll_loop(config)


if __name__ == "__main__":
    main()
