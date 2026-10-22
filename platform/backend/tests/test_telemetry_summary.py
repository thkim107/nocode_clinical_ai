"""The visible summary downloads are filtered, readable and token protected."""

import csv
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


TEST_ROOT = tempfile.TemporaryDirectory(prefix="research-agent-summary-test-")
os.environ.setdefault("AUDIT_DB_URL", "")
os.environ.setdefault("STATE_DIR", str(Path(TEST_ROOT.name, "state")))
os.environ.setdefault("DATA_DIR", str(Path(TEST_ROOT.name, "data")))

from main import app  # noqa: E402


class TelemetrySummaryTests(unittest.TestCase):
    def test_summary_requires_viewer_token(self):
        with patch.dict(os.environ, {"TELEMETRY_VIEWER_TOKEN": "test-viewer-token"}):
            response = TestClient(app).get("/api/telemetry/export/summary/runs.csv?days=7")
        self.assertEqual(response.status_code, 401)

    def test_work_summary_has_readable_columns_and_excludes_background_requests(self):
        query = AsyncMock(return_value=[{
            "session_id": "session-1", "run_id": "run-1", "subject_id": "=formula",
            "module": "planner", "operation": "research/research_plan/v2/topic/refine",
            "section": "topic", "status": "succeeded", "wall_seconds": 2.5,
            "llm_calls": 1, "input_tokens": 10, "output_tokens": 20,
            "total_tokens": 30, "tool_calls": 0, "manual_tool_calls": 0,
            "denied_tool_calls": 0, "external_calls": 0,
        }])
        with (
            patch.dict(os.environ, {"TELEMETRY_VIEWER_TOKEN": "test-viewer-token"}),
            patch("telemetry_router._query_rows", query),
        ):
            response = TestClient(app).get(
                "/api/telemetry/export/summary/runs.csv?days=7",
                headers={"X-Telemetry-Token": "test-viewer-token"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.content.startswith(b"\xef\xbb\xbf"))
        rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
        self.assertEqual(rows[0]["작업 내용"], "연구 주제 정제")
        self.assertEqual(rows[0]["탭"], "연구 계획")
        self.assertEqual(rows[0]["가명 사용자"], "'=formula")
        self.assertEqual(rows[0]["전체 토큰"], "30")
        sql, days, row_limit = query.await_args.args
        self.assertIn("r.http_method IN ('POST', 'PUT', 'PATCH', 'DELETE')", sql)
        self.assertEqual(days, 7)
        self.assertEqual(row_limit, 100_000)

    def test_session_summary_uses_period_filtered_work(self):
        query = AsyncMock(return_value=[{
            "session_id": "session-1", "work_count": 2,
            "work_seconds": 12.5, "total_tokens": 42,
        }])
        with (
            patch.dict(os.environ, {"TELEMETRY_VIEWER_TOKEN": "test-viewer-token"}),
            patch("telemetry_router._query_rows", query),
        ):
            response = TestClient(app).get(
                "/api/telemetry/export/summary/sessions.csv?days=30",
                headers={"X-Telemetry-Token": "test-viewer-token"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
        self.assertEqual(rows[0]["작업 수"], "2")
        self.assertEqual(rows[0]["작업 시간 합계(초)"], "12.5")
        self.assertEqual(rows[0]["전체 토큰"], "42")
        sql, days, _ = query.await_args.args
        self.assertIn("GROUP BY session_id", sql)
        self.assertIn("r.started_at >= now() - make_interval", sql)
        self.assertEqual(days, 30)


if __name__ == "__main__":
    unittest.main()
