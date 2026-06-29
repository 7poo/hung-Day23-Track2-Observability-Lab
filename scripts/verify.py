"""Rubric gate. Exit 0 only if all submission checkpoints pass.

Run: python3 scripts/verify.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

LAB = Path(__file__).resolve().parent.parent
SUBMISSION = LAB / "submission"


def app_base_url() -> str:
    """Resolve the app host port from the environment or the local .env file."""
    port = os.getenv("APP_PORT")
    env_file = LAB / ".env"
    if not port and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("APP_PORT="):
                port = line.split("=", 1)[1].strip()
                break
    return f"http://127.0.0.1:{port or '8000'}"


def check(label: str, ok: bool, detail: str = "") -> bool:
    icon = "[PASS]" if ok else "[FAIL]"
    line = f"{icon} {label}"
    if detail:
        line += f"  ({detail})"
    print(line)
    return ok


def http_ok(url: str, timeout: float = 3.0) -> bool:
    try:
        return requests.get(url, timeout=timeout).status_code == 200
    except requests.exceptions.RequestException:
        return False


def main() -> int:
    results: list[bool] = []
    app_url = app_base_url()

    # 00-setup
    setup_report = LAB / "00-setup" / "setup-report.json"
    results.append(check(
        "00-setup: setup-report.json committed",
        setup_report.exists(),
        f"path={setup_report}",
    ))

    # 01-instrument-fastapi
    results.append(check(
        "01: app /healthz reachable",
        http_ok(f"{app_url}/healthz"),
    ))
    results.append(check(
        "01: /metrics exposes inference_requests_total",
        any("inference_requests_total" in line
            for line in requests.get(f"{app_url}/metrics", timeout=3).text.splitlines())
        if http_ok(f"{app_url}/metrics") else False,
    ))

    # 02-prometheus-grafana
    results.append(check("02: Prometheus reachable", http_ok("http://127.0.0.1:9090/-/healthy")))
    results.append(check("02: Grafana reachable", http_ok("http://127.0.0.1:3000/api/health")))
    results.append(check("02: Alertmanager reachable", http_ok("http://127.0.0.1:9093/-/healthy")))

    # Verify dashboards loaded (Grafana API)
    try:
        r = requests.get(
            "http://127.0.0.1:3000/api/search?query=Day%2023",
            auth=("admin", "admin"),
            timeout=3,
        )
        dashboards = r.json() if r.status_code == 200 else []
        dash_count = len(dashboards)
    except Exception:
        dash_count = 0
    results.append(check(
        "02: 3 Day-23 dashboards loaded",
        dash_count >= 3,
        f"found={dash_count}",
    ))

    # 03-tracing-and-logs
    results.append(check("03: Jaeger UI reachable", http_ok("http://127.0.0.1:16686/")))
    results.append(check("03: Loki ready", http_ok("http://127.0.0.1:3100/ready")))
    results.append(check("03: OTel Collector self-metrics reachable", http_ok("http://127.0.0.1:8888/metrics")))

    # 04-drift-detection
    drift_summary = LAB / "04-drift-detection" / "reports" / "drift-summary.json"
    drift_ok = False
    if drift_summary.exists():
        try:
            data = json.loads(drift_summary.read_text(encoding="utf-8"))
            drift_ok = any(m.get("drift") == "yes" for m in data.values())
        except json.JSONDecodeError:
            pass
    results.append(check("04: drift-summary.json shows at least one drifted feature", drift_ok))

    # Submission
    reflection = SUBMISSION / "REFLECTION.md"
    results.append(check(
        "submission: REFLECTION.md exists and is non-trivial",
        reflection.exists() and len(reflection.read_text(encoding="utf-8")) > 500,
    ))

    print()
    passed = sum(results)
    total = len(results)
    print(f"Result: {passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
