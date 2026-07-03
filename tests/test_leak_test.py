from __future__ import annotations

import csv
import json

from proxy_manager.leak_test import LeakTestResult, export_csv, export_json


def _sample_results() -> list[LeakTestResult]:
    return [
        LeakTestResult(
            profile_id=1, profile_name="p1", expected_ip="1.1.1.1", observed_ip="1.1.1.1",
            ip_leak_pass=True, kill_switch_pass=True,
        ),
        LeakTestResult(
            profile_id=2, profile_name="p2", expected_ip="2.2.2.2", observed_ip=None,
            ip_leak_pass=False, kill_switch_pass=False, notes="proxy down",
        ),
    ]


def test_export_csv(tmp_path):
    path = tmp_path / "report.csv"
    export_csv(_sample_results(), path)

    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    assert rows[0]["profile_name"] == "p1"
    assert rows[0]["ip_leak_pass"] == "True"
    assert rows[1]["notes"] == "proxy down"


def test_export_json(tmp_path):
    path = tmp_path / "report.json"
    export_json(_sample_results(), path)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data) == 2
    assert data[0]["profile_name"] == "p1"
    assert data[1]["ip_leak_pass"] is False
