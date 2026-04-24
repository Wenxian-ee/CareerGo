#!/usr/bin/env bash
# Cron wrapper for jobs.ac.uk RSS crawler
# Runs a single incremental crawl, skipping jobs already in DB.
# Logs to a timestamped file + a fixed "latest" symlink.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs"
mkdir -p "$LOG_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="${LOG_DIR}/crawl_${TIMESTAMP}.log"
LATEST_LINK="${LOG_DIR}/latest.log"

PYTHON="/root/miniconda3/bin/python3"

echo "[$(date)] Starting incremental crawl ..." >> "$LOG_FILE"

"$PYTHON" "${SCRIPT_DIR}/jobs_ac_uk_rss_crawler.py" \
    --mode once \
    --feeds location \
    --skip-existing \
    --delay-min 2 \
    --delay-max 5 \
    >> "$LOG_FILE" 2>&1

EXIT_CODE=$?
echo "[$(date)] Crawl finished with exit code ${EXIT_CODE}" >> "$LOG_FILE"

# Update "latest" symlink
ln -sf "$LOG_FILE" "$LATEST_LINK"

# Keep only the last 30 log files
ls -1t "${LOG_DIR}"/crawl_*.log 2>/dev/null | tail -n +31 | xargs -r rm -f

exit $EXIT_CODE
