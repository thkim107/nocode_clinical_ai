"""Regression checks for the four user-facing tabs without external API calls."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


TEST_ROOT = tempfile.TemporaryDirectory(prefix="research-agent-tab-test-")
os.environ.setdefault("AUDIT_DB_URL", "")
os.environ.setdefault("DATA_DIR", str(Path(TEST_ROOT.name, "data")))
os.environ.setdefault("STATE_DIR", str(Path(TEST_ROOT.name, "state")))
Path(os.environ["DATA_DIR"]).mkdir(parents=True, exist_ok=True)

from main import app  # noqa: E402
from research import llm_manager  # noqa: E402


class FourTabSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        TEST_ROOT.cleanup()

    def test_telemetry_keywords_reach_the_manager_and_logger(self):
        provider = llm_manager.llm_manager._providers[llm_manager.llm_manager._current_provider]
        response = llm_manager.LLMResponse(
            text='{"ok": true}', input_tokens=3, output_tokens=4, total_tokens=7,
        )
        with (
            patch.object(provider, "get_response", return_value=response),
            patch.object(llm_manager, "audit_log_sync"),
            patch.object(llm_manager, "record_llm_call_sync") as record,
        ):
            result = llm_manager.get_response(
                "system", "user", telemetry_operation="test.operation",
                telemetry_section="test_section", telemetry_attempt=2,
                telemetry_metadata={"source": "tab_test"},
            )
        self.assertEqual(result, '{"ok": true}')
        kwargs = record.call_args.kwargs
        self.assertEqual(kwargs["operation"], "test.operation")
        self.assertEqual(kwargs["section"], "test_section")
        self.assertEqual(kwargs["attempt"], 2)
        self.assertEqual(kwargs["metadata"], {"source": "tab_test"})
        self.assertEqual(kwargs["total_tokens"], 7)

    def test_research_planner_tab(self):
        with patch.object(
            llm_manager.llm_manager, "get_response",
            return_value='{"topic_refined":"검증용 연구 주제","topic_en":"Test study"}',
        ) as manager:
            response = self.client.post(
                "/api/research/research_plan/v2/topic/refine",
                json={"user_code": "tab-test-planner", "topic_raw": "검증용 연구 주제"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["topic_refined"], "검증용 연구 주제")
        self.assertEqual(
            manager.call_args.kwargs["telemetry_operation"],
            "research_planner_v2_refine_topic",
        )

    def test_pubmed_tab(self):
        seen = []

        def llm_reply(*args, **kwargs):
            operation = kwargs.get("telemetry_operation")
            seen.append(operation)
            if operation == "pubmed.research_summary":
                return "검증용 요약"
            if operation == "pubmed.keyword_extraction":
                return '{"P":"patients","I":"biomarker","M":"model","O":"outcome"}'
            if operation == "pubmed.synonym_generation":
                return '{"P":["patients"],"I":["biomarker"],"M":["model"],"O":["outcome"]}'
            if operation == "pubmed.query_generation":
                return '{"summary_query":"test"}'
            raise AssertionError(f"unexpected LLM operation: {operation}")

        with (
            patch.object(llm_manager.llm_manager, "get_response", side_effect=llm_reply),
            patch("research.routers.pubmed._build_expanded_query_specs", return_value=[
                {"query_name": "test", "query_text": "test"},
            ]),
            patch("research.routers.pubmed.generate_pubmed_search_url", return_value="test-url"),
            patch("research.routers.pubmed.search_pubmed", return_value=[]),
            patch("research.routers.pubmed.PUBMED_API_DELAY", 0),
        ):
            response = self.client.post(
                "/api/research/pubmed_search/",
                json={
                    "user_code": "tab-test-pubmed",
                    "research_plan_background": "검증용 배경",
                    "research_plan_data_analysis_method": "검증용 방법",
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("모든 데이터가 전송되었습니다", response.text)
        self.assertEqual(seen, [
            "pubmed.research_summary", "pubmed.keyword_extraction",
            "pubmed.synonym_generation", "pubmed.query_generation",
        ])

    def test_irb_documentation_tab(self):
        with patch.object(
            llm_manager.llm_manager, "get_response",
            return_value='{"subquery1":"검증용 질문"}',
        ) as manager:
            response = self.client.post(
                "/api/research/research_plan/get_research_background_answer",
                json={
                    "user_code": "tab-test-document",
                    "irb_research_title": "검증용 연구",
                    "planner_sections": {"research_purpose": "검증용 목적"},
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["subquery1"], "검증용 질문")
        self.assertEqual(manager.call_args.kwargs["telemetry_section"], "research_background_questions")

    def test_mcp_workspace_tab(self):
        async def no_tools(*args, **kwargs):
            return [], {}

        async def model_reply(*args, **kwargs):
            return {
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "검증용 채팅 답변"}],
            }, None, "test-call-id"

        with (
            patch("chat.router.OPENROUTER_API_KEY", "test-key"),
            patch("chat.router._gather_tools", side_effect=no_tools),
            patch("chat.router._call_openrouter", side_effect=model_reply),
        ):
            response = self.client.post(
                "/api/chat/completions",
                json={"messages": [{"role": "user", "content": "검증용 질문"}], "enabled_servers": []},
            )
        self.assertEqual(response.status_code, 200, response.text)
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        self.assertTrue(any(event.get("type") == "text" and event.get("content") == "검증용 채팅 답변" for event in events))
        self.assertTrue(any(event.get("type") == "done" for event in events))
        with patch("files.path_utils.BASE_DIR", Path(os.environ["DATA_DIR"])):
            self.assertEqual(self.client.get("/api/ls").status_code, 200)


if __name__ == "__main__":
    unittest.main()
