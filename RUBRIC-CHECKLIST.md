# Day 23 Rubric Checklist

Repo URL: https://github.com/7poo/hung-Day23-Track2-Observability-Lab.git

Generated on: 2026-06-29

## Automated gate

`python scripts/verify.py` passed:

```text
Result: 12/12 checks passed
```

`make verify` could not be executed on this Windows host because `make` is not installed in PATH. The Makefile target calls `python3 scripts/verify.py`, so the equivalent rubric gate was executed directly.

## Core rubric audit

| # | Pts | Checkpoint | Status | Evidence |
|---|---:|---|---|---|
| 1 | 5 | `setup-report.json` committed | Done | `00-setup/setup-report.json` |
| 2 | 5 | `/metrics` exposes `inference_requests_total` | Done | `python scripts/verify.py` |
| 3 | 5 | `/metrics` exposes `inference_latency_seconds_bucket` | Done | App `/metrics`; verify app metrics endpoint reachable |
| 4 | 5 | `inference_active_gauge` rises/returns to 0 | Done | `submission/screenshots/dashboard-overview.png` |
| 5 | 5 | `inference_quality_score` and `inference_tokens_total` | Done | `submission/screenshots/cost-tokens.png` |
| 6 | 5 | 3 Day-23 dashboards auto-loaded | Done | Grafana API found 5 dashboard/folder entries |
| 7 | 5 | Overview dashboard 6 panels render | Done | `submission/screenshots/dashboard-overview.png` |
| 8 | 5 | SLO burn-rate dashboard populates | Done | `submission/screenshots/slo-burn-rate.png` |
| 9 | 5 | Cost dashboard non-zero $/hr | Done | `submission/screenshots/cost-tokens.png` |
| 10 | 5 | `ServiceDown` fires in Alertmanager | Done | `submission/screenshots/alertmanager-firing.png` |
| 11 | 5 | Slack fire + resolve messages | Needs real webhook | `.env` currently uses placeholder `SLACK_WEBHOOK_URL`; Alertmanager local fire/resolve verified |
| 12 | 5 | Jaeger trace for `POST /predict` with 3 child spans | Done | `submission/screenshots/jaeger-trace.png` |
| 13 | 5 | GenAI semantic span attributes | Done | `submission/screenshots/jaeger-span-attrs.png` |
| 14 | 5 | Tail-sampling evidence/math | Done | `submission/REFLECTION.md` |
| 15 | 5 | JSON log line with `trace_id` | Done | `submission/REFLECTION.md` |
| 16 | 5 | `drift-summary.json` shows drift | Done | `04-drift-detection/reports/drift-summary.json` |
| 17 | 5 | Evidently HTML report renders | Done | `04-drift-detection/reports/drift-report.html`, `submission/screenshots/evidently-drift-report.png` |
| 18 | 5 | Reflection explains PSI/KL/KS/MMD choices | Done | `submission/REFLECTION.md` |
| 19 | 5 | At least 1 prior-day source connected/stubbed | Done | Day 19/20 stubs, `submission/screenshots/cross-day-stack.png` |
| 20 | 5 | Cross-day dashboard has all 6 panels | Done | `submission/screenshots/cross-day-stack.png` |
| 21 | 5 | Reflection sections 1-5 filled | Done | `submission/REFLECTION.md` |
| 22 | 10 | “single change that mattered most” paragraph | Done | `submission/REFLECTION.md` |

## Remaining manual action

To claim rubric item #11, replace the placeholder in `.env`:

```env
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

Then restart Alertmanager and rerun the alert demo:

```bash
docker compose restart alertmanager
make alert
```

Capture Slack fire + resolve screenshots as:

- `submission/screenshots/slack-firing.png`
- `submission/screenshots/slack-resolved.png`

