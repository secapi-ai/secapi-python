import json
import os
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
    def test_loads_auth_and_base_url_from_environment_when_constructor_options_are_omitted(self):
        previous = {
            "SECAPI_API_KEY": os.environ.get("SECAPI_API_KEY"),
            "SECAPI_BASE_URL": os.environ.get("SECAPI_BASE_URL"),
        }
        try:
            os.environ["SECAPI_API_KEY"] = "env_fallback_api_key"
            os.environ["SECAPI_BASE_URL"] = "https://env.secapi.test/"

            seen = []
            client = SecApiClient(retry=False, telemetry=False)

            def opener(request, timeout=None):
                seen.append({
                    "url": request.full_url,
                    "api_key": request.headers.get("X-api-key"),
                })
                return FakeResponse(body={"ok": True})

            client._urlopen = opener
            client.latest_filing(ticker="AAPL", form="10-K")

            self.assertEqual(
                seen,
                [{
                    "url": "https://env.secapi.test/v1/filings/latest?ticker=AAPL&form=10-K",
                    "api_key": "env_fallback_api_key",
                }],
            )
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    def test_treats_blank_constructor_auth_and_base_url_values_as_missing(self):
        previous = {
            "SECAPI_API_KEY": os.environ.get("SECAPI_API_KEY"),
            "SECAPI_BASE_URL": os.environ.get("SECAPI_BASE_URL"),
        }
        try:
            os.environ["SECAPI_API_KEY"] = "env_fallback_api_key"
            os.environ["SECAPI_BASE_URL"] = "https://env.secapi.test/"

            seen = []
            client = SecApiClient(api_key=" ", base_url="", retry=False, telemetry=False)

            def opener(request, timeout=None):
                seen.append({
                    "url": request.full_url,
                    "api_key": request.headers.get("X-api-key"),
                })
                return FakeResponse(body={"ok": True})

            client._urlopen = opener
            client.latest_filing(ticker="AAPL", form="10-K")

            self.assertEqual(
                seen,
                [{
                    "url": "https://env.secapi.test/v1/filings/latest?ticker=AAPL&form=10-K",
                    "api_key": "env_fallback_api_key",
                }],
            )
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    def test_loads_compatibility_auth_and_base_url_environment_fallbacks(self):
        previous = {
            "SECAPI_API_KEY": os.environ.get("SECAPI_API_KEY"),
            "SECAPI_BASE_URL": os.environ.get("SECAPI_BASE_URL"),
            "OMNI_DATASTREAM_API_KEY": os.environ.get("OMNI_DATASTREAM_API_KEY"),
            "OMNI_DATASTREAM_BASE_URL": os.environ.get("OMNI_DATASTREAM_BASE_URL"),
            "OMNI_DATASTREAM_API_BASE_URL": os.environ.get("OMNI_DATASTREAM_API_BASE_URL"),
        }
        try:
            os.environ.pop("SECAPI_API_KEY", None)
            os.environ.pop("SECAPI_BASE_URL", None)
            os.environ["OMNI_DATASTREAM_API_KEY"] = "omni_fallback_api_key"
            os.environ.pop("OMNI_DATASTREAM_BASE_URL", None)
            os.environ["OMNI_DATASTREAM_API_BASE_URL"] = "https://omni-api.secapi.test/"

            seen = []
            client = SecApiClient(retry=False, telemetry=False)

            def opener(request, timeout=None):
                seen.append({
                    "url": request.full_url,
                    "api_key": request.headers.get("X-api-key"),
                })
                return FakeResponse(body={"ok": True})

            client._urlopen = opener
            client.latest_filing(ticker="AAPL", form="10-K")

            self.assertEqual(
                seen,
                [{
                    "url": "https://omni-api.secapi.test/v1/filings/latest?ticker=AAPL&form=10-K",
                    "api_key": "omni_fallback_api_key",
                }],
            )
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    def test_loads_compatibility_bearer_token_environment_fallback(self):
        previous = {
            "SECAPI_API_KEY": os.environ.get("SECAPI_API_KEY"),
            "SECAPI_BEARER_TOKEN": os.environ.get("SECAPI_BEARER_TOKEN"),
            "OMNI_DATASTREAM_BEARER_TOKEN": os.environ.get("OMNI_DATASTREAM_BEARER_TOKEN"),
        }
        try:
            os.environ.pop("SECAPI_API_KEY", None)
            os.environ.pop("SECAPI_BEARER_TOKEN", None)
            os.environ["OMNI_DATASTREAM_BEARER_TOKEN"] = "bearer_OMNI_FALLBACK"

            seen = []
            client = SecApiClient(retry=False, telemetry=False)

            def opener(request, timeout=None):
                seen.append(request.headers.get("Authorization"))
                return FakeResponse(body={"ok": True})

            client._urlopen = opener
            client.latest_filing(ticker="AAPL", form="10-K")

            self.assertEqual(seen, ["Bearer bearer_OMNI_FALLBACK"])
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    def test_explicit_constructor_auth_and_base_url_override_environment_fallbacks(self):
        previous = {
            "SECAPI_API_KEY": os.environ.get("SECAPI_API_KEY"),
            "SECAPI_BASE_URL": os.environ.get("SECAPI_BASE_URL"),
        }
        try:
            os.environ["SECAPI_API_KEY"] = "env_fallback_api_key"
            os.environ["SECAPI_BASE_URL"] = "https://env.secapi.test"

            seen = []
            client = SecApiClient(
                api_key="explicit_api_key",
                base_url="https://explicit.secapi.test",
                retry=False,
                telemetry=False,
            )

            def opener(request, timeout=None):
                seen.append({
                    "url": request.full_url,
                    "api_key": request.headers.get("X-api-key"),
                })
                return FakeResponse(body={"ok": True})

            client._urlopen = opener
            client.latest_filing(ticker="AAPL", form="10-K")

            self.assertEqual(
                seen,
                [{
                    "url": "https://explicit.secapi.test/v1/filings/latest?ticker=AAPL&form=10-K",
                    "api_key": "explicit_api_key",
                }],
            )
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

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

    def test_grouped_namespaces_delegate_to_flat_sdk_methods(self):
        seen_urls = []
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            seen_urls.append(request.full_url)
            return FakeResponse(body={"ok": True})

        client._urlopen = opener

        client.entities.resolve(ticker="AAPL")
        client.filings.latest(ticker="AAPL", form="10-K")
        client.sections.agent_latest("item_1a", ticker="AAPL", form="10-K", filing_year=2025)
        client.search.semantic(q="supply chain risk", ticker="AAPL", mode="hybrid", view="agent")
        client.factors.history("VALUE", range="1y", response_mode="compact", include="trust,series")
        client.factors.dashboard(country="US", category="style", ticker="AAPL", response_mode="compact")

        self.assertEqual(
            seen_urls,
            [
                "https://api.secapi.ai/v1/entities/resolve?ticker=AAPL",
                "https://api.secapi.ai/v1/filings/latest?ticker=AAPL&form=10-K",
                "https://api.secapi.ai/v1/filings/latest/sections/item_1a?mode=compact&ticker=AAPL&form=10-K&filing_year=2025",
                "https://api.secapi.ai/v1/search/semantic?q=supply+chain+risk&ticker=AAPL&mode=hybrid&view=agent",
                "https://api.secapi.ai/v1/factors/history/VALUE?range=1y&response_mode=compact&include=trust%2Cseries",
                "https://api.secapi.ai/v1/factors/dashboard?country=US&category=style&ticker=AAPL&response_mode=compact",
            ],
        )

    def test_grouped_namespaces_resolve_flat_methods_at_call_time(self):
        client = SecApiClient(retry=False, telemetry=False)

        def latest_filing(**params):
            return {"source": "patched", "params": params}

        client.latest_filing = latest_filing

        self.assertEqual(
            client.filings.latest(ticker="MSFT", form="10-Q"),
            {"source": "patched", "params": {"ticker": "MSFT", "form": "10-Q"}},
        )

    def test_paginate_filings_follows_next_cursor(self):
        seen_urls = []
        responses = [
            {"object": "list", "data": [{"accessionNumber": "0001"}, {"accessionNumber": "0002"}], "nextCursor": "cur_2"},
            {"object": "list", "data": [{"accessionNumber": "0003"}], "nextCursor": None},
        ]
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            seen_urls.append(request.full_url)
            return FakeResponse(body=responses.pop(0))

        client._urlopen = opener

        accessions = [
            filing["accessionNumber"]
            for filing in client.paginate_filings(ticker="AAPL", form="10-K", limit=2)
        ]

        self.assertEqual(accessions, ["0001", "0002", "0003"])
        self.assertEqual(
            seen_urls,
            [
                "https://api.secapi.ai/v1/filings?ticker=AAPL&form=10-K&limit=2",
                "https://api.secapi.ai/v1/filings?ticker=AAPL&form=10-K&limit=2&cursor=cur_2",
            ],
        )

    def test_paginate_sections_honors_max_items_without_extra_fetch(self):
        seen_urls = []
        responses = [
            {"object": "list", "sections": [{"contentMd": "first"}, {"contentMd": "second"}], "nextCursor": "cur_2"},
            {"object": "list", "sections": [{"contentMd": "third"}], "nextCursor": "cur_3"},
        ]
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            seen_urls.append(request.full_url)
            return FakeResponse(body=responses.pop(0))

        client._urlopen = opener

        sections = [
            section["contentMd"]
            for section in client.paginate_sections(q="risk", ticker="AAPL", limit=2, max_items=2)
        ]

        self.assertEqual(sections, ["first", "second"])
        self.assertEqual(seen_urls, ["https://api.secapi.ai/v1/sections/search?q=risk&ticker=AAPL&limit=2"])

    def test_paginate_entities_yields_entity_records(self):
        seen_urls = []
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            seen_urls.append(request.full_url)
            return FakeResponse(body={
                "object": "list",
                "data": [{"object": "entity", "id": "ent_aapl", "name": "Apple Inc.", "ticker": "AAPL"}],
                "nextCursor": None,
            })

        client._urlopen = opener

        names = [entity["name"] for entity in client.paginate_entities(q="apple", limit=1)]

        self.assertEqual(names, ["Apple Inc."])
        self.assertEqual(seen_urls, ["https://api.secapi.ai/v1/entities?q=apple&limit=1"])

    def test_generic_paginate_supports_custom_extractors(self):
        seen_urls = []
        responses = [
            {"rows": [{"id": "evt_1"}], "cursor": "event_cursor_2"},
            {"rows": [{"id": "evt_2"}], "cursor": None},
        ]
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            seen_urls.append(request.full_url)
            return FakeResponse(body=responses.pop(0))

        client._urlopen = opener

        events = [
            event["id"]
            for event in client.paginate(
                lambda **params: client.stream_events("stream_1", **params),
                {"limit": 1},
                get_items=lambda page: page["rows"],
                get_next_cursor=lambda page: page["cursor"],
            )
        ]

        self.assertEqual(events, ["evt_1", "evt_2"])
        self.assertEqual(
            seen_urls,
            [
                "https://api.secapi.ai/v1/stream_subscriptions/stream_1/events?limit=1",
                "https://api.secapi.ai/v1/stream_subscriptions/stream_1/events?cursor=event_cursor_2&limit=1",
            ],
        )

    def test_paginate_stops_when_has_more_is_false_even_with_next_cursor(self):
        seen_urls = []
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            seen_urls.append(request.full_url)
            return FakeResponse(body={
                "object": "list",
                "data": [{"accessionNumber": "0001"}],
                "hasMore": False,
                "nextCursor": "high_water_mark",
            })

        client._urlopen = opener

        accessions = [filing["accessionNumber"] for filing in client.paginate_filings(limit=1)]

        self.assertEqual(accessions, ["0001"])
        self.assertEqual(seen_urls, ["https://api.secapi.ai/v1/filings?limit=1"])

    def test_paginate_stops_when_has_more_snake_case_is_false_even_with_next_cursor(self):
        seen_urls = []
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            seen_urls.append(request.full_url)
            return FakeResponse(body={
                "object": "list",
                "data": [{"accessionNumber": "0001"}],
                "has_more": False,
                "next_cursor": "high_water_mark",
            })

        client._urlopen = opener

        accessions = [filing["accessionNumber"] for filing in client.paginate_filings(limit=1)]

        self.assertEqual(accessions, ["0001"])
        self.assertEqual(seen_urls, ["https://api.secapi.ai/v1/filings?limit=1"])

    def test_paginate_stops_on_empty_page_even_with_fresh_cursor(self):
        seen_urls = []
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            seen_urls.append(request.full_url)
            return FakeResponse(body={
                "object": "list",
                "data": [],
                "nextCursor": "cur_fresh",
            })

        client._urlopen = opener

        accessions = [filing["accessionNumber"] for filing in client.paginate_filings(limit=1)]

        self.assertEqual(accessions, [])
        self.assertEqual(seen_urls, ["https://api.secapi.ai/v1/filings?limit=1"])

    def test_paginate_raises_on_repeated_cursor(self):
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            return FakeResponse(body={"object": "list", "data": [], "nextCursor": "cur_repeat"})

        client._urlopen = opener

        with self.assertRaisesRegex(RuntimeError, "pagination cursor repeated"):
            list(client.paginate_filings(cursor="cur_repeat", limit=1))

    def test_paginate_honors_max_pages_without_extra_fetch(self):
        seen_urls = []
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            seen_urls.append(request.full_url)
            return FakeResponse(body={"object": "list", "data": [{"accessionNumber": "0001"}], "nextCursor": "cur_2"})

        client._urlopen = opener

        accessions = [
            filing["accessionNumber"]
            for filing in client.paginate_filings(limit=1, max_pages=1)
        ]

        self.assertEqual(accessions, ["0001"])
        self.assertEqual(seen_urls, ["https://api.secapi.ai/v1/filings?limit=1"])

    def test_paginate_zero_limits_are_lazy_noops(self):
        seen_urls = []
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            seen_urls.append(request.full_url)
            return FakeResponse(body={"object": "list", "data": [{"accessionNumber": "0001"}]})

        client._urlopen = opener

        self.assertEqual(list(client.paginate_filings(limit=1, max_items=0)), [])
        self.assertEqual(list(client.paginate_filings(limit=1, max_pages=0)), [])
        self.assertEqual(seen_urls, [])

    def test_paginate_preserves_request_options_without_query_params(self):
        seen_urls = []
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            seen_urls.append(request.full_url)
            return FakeResponse(body={"object": "list", "data": [{"accessionNumber": "0001"}], "nextCursor": None})

        client._urlopen = opener

        accessions = [
            filing["accessionNumber"]
            for filing in client.paginate_filings(limit=1, retry=False, telemetry=False)
        ]

        self.assertEqual(accessions, ["0001"])
        self.assertEqual(seen_urls, ["https://api.secapi.ai/v1/filings?limit=1"])

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

    def test_monitor_helpers_escape_opaque_monitor_ids(self):
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

        client.get_monitor("mon/with spaces")
        client.update_monitor_delivery("mon/with spaces", type="email", config={"to": "ops@example.com"})
        client.monitor_matches("mon/with spaces", limit=5)
        client.delete_monitor("mon/with spaces")

        self.assertEqual(
            seen,
            [
                {
                    "url": "https://api.secapi.ai/v1/monitors/mon%2Fwith%20spaces",
                    "method": "GET",
                    "body": None,
                },
                {
                    "url": "https://api.secapi.ai/v1/monitors/mon%2Fwith%20spaces/delivery",
                    "method": "POST",
                    "body": {"type": "email", "config": {"to": "ops@example.com"}},
                },
                {
                    "url": "https://api.secapi.ai/v1/monitors/mon%2Fwith%20spaces/matches?limit=5",
                    "method": "GET",
                    "body": None,
                },
                {
                    "url": "https://api.secapi.ai/v1/monitors/mon%2Fwith%20spaces",
                    "method": "DELETE",
                    "body": None,
                },
            ],
        )

    def test_statement_helper_escapes_opaque_statement_keys(self):
        seen_urls = []
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            seen_urls.append(request.full_url)
            return FakeResponse(body={"ok": True})

        client._urlopen = opener

        client.statement_by_key("income/statement with spaces", ticker="AAPL", period="annual", limit=2)

        self.assertEqual(
            seen_urls[0],
            "https://api.secapi.ai/v1/statements/income%2Fstatement%20with%20spaces?ticker=AAPL&period=annual&limit=2",
        )

    def test_filing_helpers_escape_opaque_path_ids(self):
        seen_urls = []
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            seen_urls.append(request.full_url)
            return FakeResponse(body={"ok": True})

        client._urlopen = opener

        client.filing_by_accession("0000320193/25 000079", view="agent")
        client.latest_section("item/1a risk", ticker="AAPL")
        client.filing_section_by_accession("0000320193/25 000079", "item/7 md&a", mode="compact")

        self.assertEqual(
            seen_urls,
            [
                "https://api.secapi.ai/v1/filings/0000320193%2F25%20000079?view=agent",
                "https://api.secapi.ai/v1/filings/latest/sections/item%2F1a%20risk?ticker=AAPL",
                (
                    "https://api.secapi.ai/v1/filings/0000320193%2F25%20000079"
                    "/sections/item%2F7%20md%26a?mode=compact"
                ),
            ],
        )

    def test_stream_events_escapes_opaque_stream_id(self):
        seen_urls = []
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            seen_urls.append(request.full_url)
            return FakeResponse(body={"ok": True})

        client._urlopen = opener

        client.stream_events("stream/with spaces", cursor="cur_1", type="filing.created", limit=5)

        self.assertEqual(
            seen_urls[0],
            "https://api.secapi.ai/v1/stream_subscriptions/stream%2Fwith%20spaces/events?cursor=cur_1&type=filing.created&limit=5",
        )

    def test_webhook_helpers_escape_opaque_path_ids(self):
        seen = []
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            seen.append({"url": request.full_url, "method": request.get_method()})
            return FakeResponse(body={"ok": True})

        client._urlopen = opener

        client.rotate_webhook_endpoint_secret("we/with spaces")
        client.list_webhook_deliveries("we/with spaces", event_id="evt_1", limit=2)
        client.replay_webhook_delivery("we/with spaces", "del/with spaces")

        self.assertEqual(
            seen,
            [
                {
                    "url": "https://api.secapi.ai/v1/webhook_endpoints/we%2Fwith%20spaces/rotate_secret",
                    "method": "POST",
                },
                {
                    "url": "https://api.secapi.ai/v1/webhook_endpoints/we%2Fwith%20spaces/deliveries?eventId=evt_1&limit=2",
                    "method": "GET",
                },
                {
                    "url": (
                        "https://api.secapi.ai/v1/webhook_endpoints/we%2Fwith%20spaces"
                        "/deliveries/del%2Fwith%20spaces/replay"
                    ),
                    "method": "POST",
                },
            ],
        )

    def test_artifact_helpers_escape_opaque_path_ids(self):
        seen = []
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            seen.append({"url": request.full_url, "method": request.get_method()})
            return FakeResponse(body={"ok": True})

        client._urlopen = opener

        client.get_artifact("art/with spaces")
        client.artifact_manifest("art/with spaces")
        client.export_artifact("art/with spaces", format="csv")
        client.download_artifact("art/with spaces")
        client.reconcile_artifact("art/with spaces")

        self.assertEqual(
            seen,
            [
                {
                    "url": "https://api.secapi.ai/v1/artifacts/art%2Fwith%20spaces",
                    "method": "GET",
                },
                {
                    "url": "https://api.secapi.ai/v1/artifacts/art%2Fwith%20spaces/manifest",
                    "method": "GET",
                },
                {
                    "url": "https://api.secapi.ai/v1/artifacts/art%2Fwith%20spaces/export?format=csv",
                    "method": "GET",
                },
                {
                    "url": "https://api.secapi.ai/v1/artifacts/art%2Fwith%20spaces/download",
                    "method": "GET",
                },
                {
                    "url": "https://api.secapi.ai/v1/artifacts/art%2Fwith%20spaces/reconcile",
                    "method": "POST",
                },
            ],
        )

    def test_admin_helpers_escape_opaque_path_ids(self):
        seen = []
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            seen.append({"url": request.full_url, "method": request.get_method()})
            return FakeResponse(body={"ok": True})

        client._urlopen = opener

        client.delete_api_key("key/with spaces")
        client.get_admin_organization("org/with spaces", limit=2)
        client.get_admin_request_diagnostics("org/with spaces", "req/with spaces")
        client.get_admin_delivery_summary("org/with spaces", since="2026-06-01T00:00:00Z", limit=3)

        self.assertEqual(
            seen,
            [
                {
                    "url": "https://api.secapi.ai/v1/api_keys/key%2Fwith%20spaces",
                    "method": "DELETE",
                },
                {
                    "url": "https://api.secapi.ai/v1/admin/orgs/org%2Fwith%20spaces?limit=2",
                    "method": "GET",
                },
                {
                    "url": (
                        "https://api.secapi.ai/v1/admin/orgs/org%2Fwith%20spaces"
                        "/requests/req%2Fwith%20spaces"
                    ),
                    "method": "GET",
                },
                {
                    "url": (
                        "https://api.secapi.ai/v1/admin/orgs/org%2Fwith%20spaces"
                        "/deliveries/summary?since=2026-06-01T00%3A00%3A00Z&limit=3"
                    ),
                    "method": "GET",
                },
            ],
        )

    def test_stock_loadings_escapes_ticker_path_segment(self):
        seen_urls = []
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            seen_urls.append(request.full_url)
            return FakeResponse(body={"ok": True})

        client._urlopen = opener

        client.stock_loadings("BRK/B", factors="VALUE", view="agent")

        self.assertEqual(
            seen_urls[0],
            "https://api.secapi.ai/v1/stocks/BRK%2FB/loadings?factors=VALUE&view=agent",
        )

    def test_model_portfolio_factor_view_escapes_portfolio_id_path_segment(self):
        seen_urls = []
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            seen_urls.append(request.full_url)
            return FakeResponse(body={"ok": True})

        client._urlopen = opener

        client.model_portfolio_factor_view("portfolio/with spaces", view="agent")

        self.assertEqual(
            seen_urls[0],
            "https://api.secapi.ai/v1/model-portfolios/portfolio%2Fwith%20spaces/factor-view?view=agent",
        )

    def test_dilution_event_detail_escapes_event_id_path_segment(self):
        seen_urls = []
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            seen_urls.append(request.full_url)
            return FakeResponse(body={"ok": True})

        client._urlopen = opener

        client.dilution_event_detail("event/with spaces", view="agent")

        self.assertEqual(
            seen_urls[0],
            "https://api.secapi.ai/v1/dilution/events/event%2Fwith%20spaces?view=agent",
        )


if __name__ == "__main__":
    unittest.main()
