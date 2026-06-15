import json
import unittest

from secapi_client import OmniDatastreamClient, OmniDatastreamError, SecApiClient, SecApiError
from omni_datastream_py import OmniDatastreamClient as LegacyOmniDatastreamClient
from omni_datastream_py import SecApiClient as LegacySecApiClient
from omni_datastream_py.client import SecApiClient as LegacySubmoduleSecApiClient


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status = status
        self.body = body if body is not None else {"ok": True}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.body).encode("utf-8")

class AgentHelperTests(unittest.TestCase):
    def test_legacy_omni_datastream_aliases_are_preserved(self):
        self.assertIs(OmniDatastreamClient, SecApiClient)
        self.assertIs(OmniDatastreamError, SecApiError)
        self.assertIs(LegacyOmniDatastreamClient, SecApiClient)
        self.assertIs(LegacySecApiClient, SecApiClient)
        self.assertIs(LegacySubmoduleSecApiClient, SecApiClient)
        self.assertIsInstance(OmniDatastreamClient(retry=False, telemetry=False), SecApiClient)

    def test_agent_helpers_default_to_compact_agent_response_shapes(self):
        seen_urls = []
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            seen_urls.append(request.full_url)
            return FakeResponse(body={"ok": True})

        client._urlopen = opener

        client.agent_latest_filing(ticker="AAPL", form="10-K")
        client.agent_statement("income_statement", ticker="AAPL", period="annual", limit=2)
        client.agent_institutional_holders(ticker="NVDA", limit=5)
        client.agent_form_144(ticker="NVDA", limit=5)
        client.agent_section("item_1a", ticker="AAPL", form="10-K", filing_year=2025)
        client.semantic_search(q="supply chain risk", ticker="AAPL", form="10-K", mode="hybrid", limit=5, view="agent")
        client.market_earnings_calendar(ticker="AAPL", date_from="2026-06-08", date_to="2026-06-15")

        self.assertEqual(seen_urls[0], "https://api.secapi.ai/v1/filings/latest?ticker=AAPL&form=10-K&view=agent")
        self.assertEqual(seen_urls[1], "https://api.secapi.ai/v1/statements/income_statement?ticker=AAPL&period=annual&limit=2&view=agent")
        self.assertEqual(seen_urls[2], "https://api.secapi.ai/v1/owners/institutional/ticker?ticker=NVDA&limit=5&view=agent")
        self.assertEqual(seen_urls[3], "https://api.secapi.ai/v1/forms/144?ticker=NVDA&limit=5&view=agent")
        self.assertEqual(seen_urls[4], "https://api.secapi.ai/v1/filings/latest/sections/item_1a?mode=compact&ticker=AAPL&form=10-K&filing_year=2025")
        self.assertEqual(seen_urls[5], "https://api.secapi.ai/v1/search/semantic?q=supply+chain+risk&ticker=AAPL&form=10-K&mode=hybrid&limit=5&view=agent")
        self.assertEqual(seen_urls[6], "https://api.secapi.ai/v1/market/earnings-calendar?ticker=AAPL&date_from=2026-06-08&date_to=2026-06-15")

    def test_search_helpers_reach_fulltext_and_vector_endpoints(self):
        seen_urls = []
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            seen_urls.append(request.full_url)
            return FakeResponse(body={"ok": True})

        client._urlopen = opener

        client.search_fulltext(q="going concern", form="10-K", limit=10)
        client.semantic_search(q="going concern", mode="keyword", filing_year=2025, limit=10)

        self.assertEqual(seen_urls[0], "https://api.secapi.ai/v1/search/fulltext?q=going+concern&form=10-K&limit=10")
        self.assertEqual(seen_urls[1], "https://api.secapi.ai/v1/search/semantic?q=going+concern&mode=keyword&filing_year=2025&limit=10")

    def test_call_mcp_tool_builds_jsonrpc_tools_call_envelope(self):
        seen_bodies = []
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            seen_bodies.append(json.loads(request.data.decode("utf-8")))
            return FakeResponse(body={"result": {"content": []}})

        client._urlopen = opener

        client.call_mcp_tool("filings.latest", {"ticker": "AAPL", "form": "10-K"}, id="agent-test")

        self.assertEqual(
            seen_bodies[0],
            {
                "jsonrpc": "2.0",
                "id": "agent-test",
                "method": "tools/call",
                "params": {
                    "name": "filings.latest",
                    "arguments": {"ticker": "AAPL", "form": "10-K"},
                },
            },
        )

    def test_monitor_helpers_use_current_flat_sdk_surface(self):
        seen = []
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            seen.append({
                "url": request.full_url,
                "method": request.get_method(),
                "body": json.loads(request.data.decode("utf-8")) if request.data else None,
            })
            return FakeResponse(body={"ok": True})

        client._urlopen = opener

        client.create_webhook_endpoint(
            destination_url="https://example.com/webhooks/filings",
            subscribed_event_types=["monitor.match"],
            description="Filing monitor webhook",
        )
        client.create_monitor(
            name="FAANG 8-K Monitor",
            query="latest 8-K filings",
            filters={"forms": ["8-K", "8-K/A"], "tickers": ["AAPL", "AMZN"]},
        )
        client.monitor_matches("mon_123", limit=5)

        self.assertEqual(
            seen[0],
            {
                "url": "https://api.secapi.ai/v1/webhook_endpoints",
                "method": "POST",
                "body": {
                    "destinationUrl": "https://example.com/webhooks/filings",
                    "description": "Filing monitor webhook",
                    "subscribedEventTypes": ["monitor.match"],
                    "livemode": None,
                },
            },
        )
        self.assertEqual(
            seen[1],
            {
                "url": "https://api.secapi.ai/v1/monitors",
                "method": "POST",
                "body": {
                    "name": "FAANG 8-K Monitor",
                    "query": "latest 8-K filings",
                    "filters": {"forms": ["8-K", "8-K/A"], "tickers": ["AAPL", "AMZN"]},
                    "searchMode": None,
                    "webhookUrl": None,
                    "delivery": None,
                },
            },
        )
        self.assertEqual(
            seen[2],
            {
                "url": "https://api.secapi.ai/v1/monitors/mon_123/matches?limit=5",
                "method": "GET",
                "body": None,
            },
        )


if __name__ == "__main__":
    unittest.main()
