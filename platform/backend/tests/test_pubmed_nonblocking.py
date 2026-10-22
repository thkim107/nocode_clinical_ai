"""PubMed's synchronous E-Utilities client must not stall the ASGI event loop."""

import asyncio
import threading
import unittest
from unittest.mock import AsyncMock, patch

from research.routers import pubmed


class PubMedNonblockingTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_and_metadata_leave_event_loop_responsive(self):
        search_started = threading.Event()
        search_release = threading.Event()
        metadata_started = threading.Event()
        metadata_release = threading.Event()

        def search(_url):
            search_started.set()
            search_release.wait(timeout=1)
            return ["12345"]

        def metadata(_pmid):
            metadata_started.set()
            metadata_release.wait(timeout=1)
            return {"Title": "Test paper", "Abstract": "Test abstract"}

        async def llm_reply(_system, _user, *, operation, **_kwargs):
            return {
                "pubmed.research_summary": "Test summary",
                "pubmed.keyword_extraction": '{"P":"patient","I":"test","M":"model","O":"outcome"}',
                "pubmed.synonym_generation": "{}",
                "pubmed.query_generation": '{"summary_query":"test"}',
            }[operation]

        async def consume():
            response = await pubmed.get_pubmed_search(pubmed.PubmedSearchData(user_code="test"))
            return [chunk async for chunk in response.body_iterator]

        with (
            patch.object(pubmed, "_llm_response", side_effect=llm_reply),
            patch.object(pubmed, "_build_expanded_query_specs", return_value=[{"query_name": "test", "query_text": "test"}]),
            patch.object(pubmed, "generate_pubmed_search_url", return_value="test-url"),
            patch.object(pubmed, "search_pubmed", side_effect=search),
            patch.object(pubmed, "get_pubmed_metadata", side_effect=metadata),
            patch.object(pubmed, "_rule_based_filter", return_value=(False, "filtered")),
            patch.object(pubmed, "record_event", new_callable=AsyncMock),
            patch.object(pubmed.session_store, "set_user_data"),
            patch.object(pubmed, "PUBMED_API_DELAY", 0),
        ):
            task = asyncio.create_task(consume())
            try:
                await asyncio.sleep(0.05)
                self.assertTrue(search_started.is_set())
                self.assertFalse(search_release.is_set())
                self.assertFalse(task.done(), "search blocked the event loop")

                search_release.set()
                await asyncio.sleep(0.05)
                self.assertTrue(metadata_started.is_set())
                self.assertFalse(metadata_release.is_set())
                self.assertFalse(task.done(), "metadata fetch blocked the event loop")

                metadata_release.set()
                chunks = await asyncio.wait_for(task, timeout=2)
                self.assertTrue(any("모든 데이터가 전송되었습니다" in chunk for chunk in chunks))
            finally:
                search_release.set()
                metadata_release.set()
                if not task.done():
                    await asyncio.wait_for(task, timeout=2)


if __name__ == "__main__":
    unittest.main()
