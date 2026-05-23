#!/bin/bash
# Orchestrator cron wrapper — invoke every 5-10 minutes
# Usage: */5 * * * * /Users/jared/dev/issuesdb-plugin/scripts/work-queue.sh
#
# The orchestrator processes one item per phase per invocation. Cron repetition
# provides the loop — each tick picks up where the last one left off.

LOG_FILE="${HOME}/Library/Logs/issue-worker.log"
MAX_LOG_SIZE_MB=10

# Rotate log if over max size
if [ -f "$LOG_FILE" ]; then
    size=$(stat -f%z "$LOG_FILE" 2>/dev/null || echo 0)
    if [ "$size" -gt $((MAX_LOG_SIZE_MB * 1024 * 1024)) ]; then
        mv "$LOG_FILE" "${LOG_FILE}.1"
    fi
fi

echo "[$(date -Iseconds)] Starting orchestrator run" >> "$LOG_FILE"

opencode run --cd /Users/jared/dev --prompt "/orchestrate" >> "$LOG_FILE" 2>&1
exit_code=$?

echo "[$(date -Iseconds)] Orchestrator run complete (exit: $exit_code)" >> "$LOG_FILE"
exit $exit_code
