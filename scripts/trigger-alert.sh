#!/usr/bin/env bash
## Trigger an alert by killing the app, wait for it to fire, then restore.
## Used in: deck §10 demo, lab Track 02 grading checkpoint.

set -euo pipefail

echo "Step 1: kill app container"
docker stop day23-app >/dev/null

echo "Step 2: wait 90s for ServiceDown alert to fire"
for i in {1..18}; do
  sleep 5
  alerts=$(curl -fsS http://127.0.0.1:9093/api/v2/alerts 2>/dev/null | grep -c '"state":"active"' || true)
  if [ "$alerts" -gt 0 ]; then
    echo "  alert fired (after ${i}*5s)"
    break
  fi
  echo "  no alert yet (${i}*5s)"
done

echo "Step 3: restart app"
docker start day23-app >/dev/null

echo "Step 4: wait 60s for alert to resolve"
for i in {1..12}; do
  sleep 5
  alerts=$(curl -fsS http://127.0.0.1:9093/api/v2/alerts 2>/dev/null | grep -c '"state":"active"' || true)
  if [ "$alerts" -eq 0 ]; then
    echo "  alert resolved"
    exit 0
  fi
done

echo "alert did not resolve within 60s" >&2
exit 1
