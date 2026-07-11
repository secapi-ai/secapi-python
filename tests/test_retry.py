import io
import json
import pathlib
import tomllib
import unittest
from email.message import Message
from urllib.error import HTTPError, URLError

from secapi_client import SecApiClient, SecApiError
from secapi_client.client import SDK_VERSION


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status = status
        self.body = body if body is not None else {"ok": True}
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.body).encode("utf-8")

    def close(self):
        self.closed = True


def http_error(status, body=None, headers=None):
    message = Message()
    for key, value in (headers or {}).items():
        message[key] = value
    return HTTPError(
        "https://api.secapi.ai/test",
        status,
        "error",
        message,
        io.BytesIO(json.dumps(body if body is not None else {"message": "error"}).encode("utf-8")),
    )


def retry_harness(**overrides):
    delays = []
    retry = {
        "sleep": delays.append,
        "random": lambda: 1.0,
        **overrides,
    }
    return retry, delays


class RetryTests(unittest.TestCase):
    def test_sdk_version_matches_package_metadata(self):
        pyproject = pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml"
        package = tomllib.loads(pyproject.read_text())

        self.assertEqual(SDK_VERSION, package["project"]["version"])

    def test_sends_secapi_version_header(self):
        captured = []
        client = SecApiClient(api_version="2026-05-20", retry=False, telemetry=False)

        def opener(request, timeout=None):
            captured.append(dict(request.header_items()))
            return FakeResponse(body={"ok": True})

        client._urlopen = opener

        self.assertEqual(client.health(), {"ok": True})
        headers = {key.lower(): value for key, value in captured[0].items()}
        self.assertEqual(headers["secapi-version"], "2026-05-20")
        self.assertEqual(headers["user-agent"], f"secapi-python/{SDK_VERSION}")
        self.assertNotIn("-".join(["omni", "version"]), headers)

    def test_retries_safe_get_on_5xx(self):
        attempts = []
        retry, delays = retry_harness()
        client = SecApiClient(retry=retry, telemetry=False)

        def opener(request, timeout=None):
            attempts.append((request, timeout))
            if len(attempts) == 1:
                raise http_error(502, {"message": "bad gateway"})
            return FakeResponse(body={"ok": True})

        client._urlopen = opener

        self.assertEqual(client.health(), {"ok": True})
        self.assertEqual(len(attempts), 2)
        self.assertEqual(delays, [200])

    def test_retries_safe_get_on_network_error(self):
        attempts = 0
        retry, delays = retry_harness(random=lambda: 0.5)
        client = SecApiClient(retry=retry, telemetry=False)

        def opener(_request, timeout=None):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise URLError("network down")
            return FakeResponse(body={"ok": True})

        client._urlopen = opener

        self.assertEqual(client.me(), {"ok": True})
        self.assertEqual(attempts, 2)
        self.assertEqual(delays, [100])

    def test_does_not_retry_nonretryable_4xx(self):
        attempts = 0
        retry, _delays = retry_harness()
        client = SecApiClient(retry=retry, telemetry=False)

        def opener(_request, timeout=None):
            nonlocal attempts
            attempts += 1
            raise http_error(400, {"message": "bad request"})

        client._urlopen = opener

        with self.assertRaises(SecApiError) as ctx:
            client.health()
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(attempts, 1)

    def test_api_error_exposes_support_diagnostics_from_payload(self):
        error = SecApiError(
            400,
            {
                "code": "invalid_request",
                "message": "ticker is required",
                "requestId": "req_payload_123",
            },
        )

        self.assertEqual(error.code, "invalid_request")
        self.assertEqual(error.message, "ticker is required")
        self.assertEqual(error.request_id, "req_payload_123")
        self.assertEqual(error.status_code, 400)
        self.assertEqual(error.body["code"], "invalid_request")
        self.assertIs(error.body, error.payload)
        self.assertIs(error.json_body, error.payload)
        self.assertEqual(error.error_code, "invalid_request")
        self.assertEqual(error.requestId, "req_payload_123")
        self.assertEqual(
            str(error),
            "SecApiError(status=400, code=invalid_request, message=ticker is required, request_id=req_payload_123)",
        )

    def test_api_error_exposes_nested_error_diagnostics(self):
        error = SecApiError(
            502,
            {
                "request_id": "req_nested_456",
                "error": {
                    "code": "mcp_tool_failed",
                    "message": "hosted tool failed",
                },
            },
        )

        self.assertEqual(error.code, "mcp_tool_failed")
        self.assertEqual(error.message, "hosted tool failed")
        self.assertEqual(error.request_id, "req_nested_456")

    def test_api_error_string_omits_request_id_when_missing(self):
        error = SecApiError(400, {"message": "bad request"})

        self.assertEqual(str(error), "SecApiError(status=400, code=None, message=bad request)")

    def test_api_error_uses_request_id_header_when_payload_omits_it(self):
        attempts = 0
        client = SecApiClient(retry=False, telemetry=False)

        def opener(_request, timeout=None):
            nonlocal attempts
            attempts += 1
            raise http_error(
                429,
                {"errorCode": "rate_limited", "detail": "retry later"},
                {"X-Request-Id": "req_header_789"},
            )

        client._urlopen = opener

        with self.assertRaises(SecApiError) as ctx:
            client.health()
        self.assertEqual(ctx.exception.code, "rate_limited")
        self.assertEqual(ctx.exception.message, "retry later")
        self.assertEqual(ctx.exception.request_id, "req_header_789")
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(ctx.exception.requestId, "req_header_789")
        self.assertIn("request_id=req_header_789", str(ctx.exception))
        self.assertEqual(attempts, 1)

    def test_default_timeout_applies_when_retries_are_disabled(self):
        timeouts = []
        client = SecApiClient(retry=False, telemetry=False)

        def opener(_request, timeout="not-passed"):
            timeouts.append(timeout)
            return FakeResponse(body={"ok": True})

        client._urlopen = opener

        self.assertEqual(client.health(), {"ok": True})
        self.assertEqual(timeouts, [30.0])

    def test_custom_timeout_applies_when_retries_are_disabled(self):
        timeouts = []
        client = SecApiClient(retry=False, telemetry=False, timeout=7.5)

        def opener(_request, timeout="not-passed"):
            timeouts.append(timeout)
            return FakeResponse(body={"ok": True})

        client._urlopen = opener

        self.assertEqual(client.health(), {"ok": True})
        self.assertEqual(timeouts, [7.5])

    def test_timeout_can_be_disabled_for_custom_transport_owners(self):
        timeouts = []
        client = SecApiClient(retry=False, telemetry=False, timeout=None)

        def opener(_request, timeout="not-passed"):
            timeouts.append(timeout)
            return FakeResponse(body={"ok": True})

        client._urlopen = opener

        self.assertEqual(client.health(), {"ok": True})
        self.assertEqual(timeouts, ["not-passed"])

    def test_timeout_none_omits_urlopen_timeout_even_with_retries_enabled(self):
        timeouts = []
        client = SecApiClient(telemetry=False, timeout=None)

        def opener(_request, timeout="not-passed"):
            timeouts.append(timeout)
            return FakeResponse(body={"ok": True})

        client._urlopen = opener

        self.assertEqual(client.health(), {"ok": True})
        self.assertEqual(timeouts, ["not-passed"])

    def test_retry_budget_clamps_longer_request_timeout(self):
        timeouts = []
        retry, _delays = retry_harness(total_budget_ms=1000, now=lambda: 1_000.0)
        client = SecApiClient(retry=retry, telemetry=False, timeout=10)

        def opener(_request, timeout="not-passed"):
            timeouts.append(timeout)
            return FakeResponse(body={"ok": True})

        client._urlopen = opener

        self.assertEqual(client.health(), {"ok": True})
        self.assertEqual(timeouts, [1.0])

    def test_per_call_opt_out_still_sends_default_timeout(self):
        attempts = 0
        timeouts = []
        retry, _delays = retry_harness()
        client = SecApiClient(retry=retry, telemetry=False)

        def opener(_request, timeout="not-passed"):
            nonlocal attempts
            attempts += 1
            timeouts.append(timeout)
            raise http_error(503, {"message": "unavailable"})

        client._urlopen = opener

        with self.assertRaises(SecApiError):
            client.health(retry=False)
        self.assertEqual(attempts, 1)
        self.assertEqual(timeouts, [30.0])

    def test_situations_namespace_preserves_per_call_retry_and_telemetry_controls(self):
        attempts = 0
        retry, _delays = retry_harness()
        client = SecApiClient(retry=retry, telemetry=False)

        def opener(request, timeout=None):
            nonlocal attempts
            attempts += 1
            self.assertNotIn("retry=", request.full_url)
            self.assertNotIn("telemetry=", request.full_url)
            raise http_error(503, {"message": "unavailable"})

        client._urlopen = opener

        with self.assertRaises(SecApiError):
            client.situations.issues(limit=2, retry=False, telemetry=False)
        self.assertEqual(attempts, 1)

        seen_urls = []

        def successful_opener(request, timeout=None):
            seen_urls.append(request.full_url)
            return FakeResponse(body={"ok": True})

        client._urlopen = successful_opener
        self.assertEqual(
            client.situations.issue(
                "issue/with spaces",
                response_mode="compact",
                retry=False,
                telemetry=False,
            ),
            {"ok": True},
        )
        self.assertEqual(
            seen_urls,
            [
                "https://api.secapi.ai/v1/situations/issues/issue%2Fwith%20spaces?response_mode=compact",
            ],
        )

    def test_get_trace_escapes_trace_id_path_segment(self):
        seen_urls = []
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            seen_urls.append(request.full_url)
            return FakeResponse(body={"ok": True})

        client._urlopen = opener

        self.assertEqual(client.get_trace("trace/with spaces"), {"ok": True})
        self.assertEqual(seen_urls[0], "https://api.secapi.ai/v1/traces/trace%2Fwith%20spaces")

    def test_request_diagnostics_escapes_request_id_path_segment(self):
        seen_urls = []
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            seen_urls.append(request.full_url)
            return FakeResponse(body={"ok": True})

        client._urlopen = opener

        self.assertEqual(client.request_diagnostics("req/with spaces"), {"ok": True})
        self.assertEqual(seen_urls[0], "https://api.secapi.ai/v1/diagnostics/requests/req%2Fwith%20spaces")

    def test_unsafe_post_503_requires_opt_in(self):
        attempts = 0
        retry, _delays = retry_harness()
        client = SecApiClient(retry=retry, telemetry=False)

        def opener(_request, timeout=None):
            nonlocal attempts
            attempts += 1
            raise http_error(503, {"message": "unavailable"})

        client._urlopen = opener

        with self.assertRaises(SecApiError):
            client.create_artifact({"kind": "audit"})
        self.assertEqual(attempts, 1)

    def test_per_call_opt_in_overrides_global_retry_false(self):
        attempts = 0
        seen_keys = []
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            nonlocal attempts
            attempts += 1
            seen_keys.append(request.get_header("Idempotency-key"))
            if attempts == 1:
                raise http_error(503, {"message": "unavailable"})
            return FakeResponse(body={"ok": True})

        client._urlopen = opener

        result = client.create_artifact(
            {"kind": "audit"},
            retry={"enabled": True, "idempotency_key": "idem_global_off"},
        )
        self.assertEqual(result, {"ok": True})
        self.assertEqual(attempts, 2)
        self.assertEqual(seen_keys, ["idem_global_off", "idem_global_off"])

    def test_body_only_methods_accept_per_call_retry_options(self):
        attempts = 0
        seen_keys = []
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            nonlocal attempts
            attempts += 1
            seen_keys.append(request.get_header("Idempotency-key"))
            if attempts == 1:
                raise http_error(503, {"message": "unavailable"})
            return FakeResponse(body={"ok": True})

        client._urlopen = opener

        result = client.portfolio_analyze(
            {"positions": []},
            retry={"enabled": True, "idempotency_key": "idem_portfolio"},
        )
        self.assertEqual(result, {"ok": True})
        self.assertEqual(attempts, 2)
        self.assertEqual(seen_keys, ["idem_portfolio", "idem_portfolio"])

    def test_watchlist_accepts_explicit_retry_options_and_params(self):
        attempts = 0
        seen_keys = []
        seen_urls = []
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            nonlocal attempts
            attempts += 1
            seen_keys.append(request.get_header("Idempotency-key"))
            seen_urls.append(request.full_url)
            if attempts == 1:
                raise http_error(503, {"message": "unavailable"})
            return FakeResponse(body={"ok": True})

        client._urlopen = opener

        result = client.intelligence_watchlist(
            {"symbols": ["AAPL"]},
            view="agent",
            retry={"enabled": True, "idempotency_key": "idem_watchlist"},
        )
        self.assertEqual(result, {"ok": True})
        self.assertEqual(attempts, 2)
        self.assertEqual(seen_keys, ["idem_watchlist", "idem_watchlist"])
        self.assertTrue(all("view=agent" in url for url in seen_urls))

    def test_negative_max_retries_still_attempts_once(self):
        attempts = 0
        retry, _delays = retry_harness(max_retries=-1)
        client = SecApiClient(retry=retry, telemetry=False)

        def opener(_request, timeout=None):
            nonlocal attempts
            attempts += 1
            raise http_error(503, {"message": "unavailable"})

        client._urlopen = opener

        with self.assertRaises(SecApiError):
            client.health()
        self.assertEqual(attempts, 1)

    def test_429_retries_unsafe_method_and_honors_retry_after(self):
        attempts = 0
        retry, delays = retry_harness()
        client = SecApiClient(retry=retry, telemetry=False)

        def opener(_request, timeout=None):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise http_error(429, {"message": "rate limited"}, {"Retry-After": "2"})
            return FakeResponse(body={"ok": True})

        client._urlopen = opener

        self.assertEqual(client.create_artifact({"kind": "audit"}), {"ok": True})
        self.assertEqual(attempts, 2)
        self.assertEqual(delays, [2000])

    def test_429_retry_after_infinity_falls_back_to_backoff(self):
        attempts = 0
        retry, delays = retry_harness()
        client = SecApiClient(retry=retry, telemetry=False)

        def opener(_request, timeout=None):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise http_error(429, {"message": "rate limited"}, {"Retry-After": "Infinity"})
            return FakeResponse(body={"ok": True})

        client._urlopen = opener

        self.assertEqual(client.create_artifact({"kind": "audit"}), {"ok": True})
        self.assertEqual(attempts, 2)
        self.assertEqual(delays, [200])

    def test_unsafe_429_terminal_failures_open_circuit(self):
        now = 0
        attempts = 0
        retry, _delays = retry_harness(max_retries=0, now=lambda: now)
        client = SecApiClient(retry=retry, telemetry=False)

        def opener(_request, timeout=None):
            nonlocal attempts
            attempts += 1
            raise http_error(429, {"message": "rate limited"})

        client._urlopen = opener

        for _ in range(5):
            with self.assertRaises(SecApiError) as ctx:
                client.create_artifact({"kind": "audit"})
            self.assertEqual(ctx.exception.status, 429)
        self.assertEqual(client.circuit_state["state"], "open")
        with self.assertRaises(SecApiError) as ctx:
            client.create_artifact({"kind": "audit"})
        self.assertEqual(ctx.exception.payload["code"], "client_circuit_open")
        self.assertEqual(attempts, 5)

    def test_mcp_retries_only_with_explicit_opt_in_and_idempotency_key(self):
        attempts = 0
        seen_keys = []
        retry, _delays = retry_harness()
        client = SecApiClient(retry=retry, telemetry=False)

        def opener(request, timeout=None):
            nonlocal attempts
            attempts += 1
            seen_keys.append(request.get_header("Idempotency-key"))
            if attempts < 3:
                raise http_error(503, {"message": "unavailable"})
            return FakeResponse(body={"ok": True})

        client._urlopen = opener

        result = client.mcp({"method": "tools/call"}, retry={"enabled": True, "idempotency_key": "idem_123"})
        self.assertEqual(result, {"ok": True})
        self.assertEqual(attempts, 3)
        self.assertEqual(seen_keys, ["idem_123", "idem_123", "idem_123"])

    def test_circuit_opens_and_half_opens_after_cooldown(self):
        now = 0
        attempts = 0
        retry, _delays = retry_harness(max_retries=0, now=lambda: now)
        client = SecApiClient(retry=retry, telemetry=False)

        def opener(_request, timeout=None):
            nonlocal attempts
            attempts += 1
            if attempts <= 5:
                raise http_error(503, {"message": "unavailable"})
            return FakeResponse(body={"ok": True})

        client._urlopen = opener

        for _ in range(5):
            with self.assertRaises(SecApiError):
                client.health()
        self.assertEqual(client.circuit_state["state"], "open")
        with self.assertRaises(SecApiError) as ctx:
            client.health()
        self.assertEqual(ctx.exception.payload["code"], "client_circuit_open")
        self.assertEqual(attempts, 5)

        now = 60_000
        self.assertEqual(client.health(), {"ok": True})
        self.assertEqual(client.circuit_state["state"], "closed")

    def test_emits_sanitized_retry_telemetry(self):
        attempts = 0
        telemetry_payloads = []
        telemetry_responses = []
        retry, _delays = retry_harness()

        def telemetry_opener(request, timeout=None):
            telemetry_payloads.append(json.loads(request.data.decode("utf-8")))
            response = FakeResponse(body={"ok": True})
            telemetry_responses.append(response)
            return response

        client = SecApiClient(
            api_key="ods_secret",
            retry=retry,
            telemetry={"capture_token": "phc_test", "distinct_id": "sdk-test", "opener": telemetry_opener, "sync": True},
        )

        def opener(_request, timeout=None):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise http_error(502, {"message": "bad gateway"})
            return FakeResponse(body={"ok": True})

        client._urlopen = opener

        self.assertEqual(client.latest_filing(ticker="AAPL", form="10-K"), {"ok": True})
        self.assertEqual(len(telemetry_payloads), 1)
        self.assertEqual(len(telemetry_responses), 1)
        self.assertTrue(telemetry_responses[0].closed)
        payload = telemetry_payloads[0]
        self.assertEqual(payload["event"], "client_retry_attempt")
        self.assertEqual(payload["api_key"], "phc_test")
        self.assertEqual(payload["distinct_id"], "sdk-test")
        self.assertEqual(payload["properties"]["sdk_language"], "py")
        self.assertEqual(payload["properties"]["sdk_version"], SDK_VERSION)
        self.assertEqual(payload["properties"]["route"], "/v1/filings/latest")
        self.assertEqual(payload["properties"]["status"], 502)
        self.assertFalse(payload["properties"]["$process_person_profile"])
        serialized = json.dumps(payload)
        self.assertNotIn("ods_secret", serialized)
        self.assertNotIn("AAPL", serialized)


class List13fFilingsTests(unittest.TestCase):
    """OMNI-3772: thin coverage on the new list_13f_filings SDK method."""

    def test_list_13f_filings_routes_to_endpoint(self):
        seen_urls = []
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            seen_urls.append(request.full_url)
            return FakeResponse(
                body={
                    "object": "list",
                    "data": [
                        {"reportDate": "2024-12-31", "filingDate": "2025-02-14"},
                        {"reportDate": "2024-09-30", "filingDate": "2024-11-15"},
                    ],
                }
            )

        client._urlopen = opener
        result = client.list_13f_filings(cik="0001067983", limit=12)
        self.assertEqual(len(result["data"]), 2)
        self.assertIn("/v1/owners/13f/filings", seen_urls[0])
        self.assertIn("cik=0001067983", seen_urls[0])
        self.assertIn("limit=12", seen_urls[0])

    def test_list_13f_filings_with_since_filter(self):
        # OMNI-3770: the SDK accepts the optional `since` filter for
        # incremental polling. Server-side support lands in a separate
        # PR; the SDK passes the param transparently so existing callers
        # don't need to wait for both PRs to land in lockstep.
        seen_urls = []
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            seen_urls.append(request.full_url)
            return FakeResponse(body={"object": "list", "data": []})

        client._urlopen = opener
        client.list_13f_filings(cik="0001067983", since="2026-05-01T00:00:00Z")
        self.assertIn("since=", seen_urls[0])

    def test_list_13f_filings_omits_none_params(self):
        seen_urls = []
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            seen_urls.append(request.full_url)
            return FakeResponse(body={"object": "list", "data": []})

        client._urlopen = opener
        client.list_13f_filings(cik="0001067983")
        # None-valued params should NOT appear in the URL.
        self.assertNotIn("limit=", seen_urls[0])
        self.assertNotIn("since=", seen_urls[0])


class FactorParityWrapperTests(unittest.TestCase):
    def test_factor_parity_wrappers_route_to_launch_paths(self):
        seen = []
        client = SecApiClient(retry=False, telemetry=False)

        def opener(request, timeout=None):
            body = request.data.decode("utf-8") if request.data else ""
            seen.append((request.get_method(), request.full_url, body))
            return FakeResponse(body={"ok": True})

        client._urlopen = opener

        client.factor_history("MKT/US", range="1y", response_mode="compact")
        client.factor_sparklines(factors=["MOMENTUM", "VALUE"], points=32)
        client.factor_extreme_moves(category="style", side="both")
        client.factor_extreme_pairs(factors=["MOMENTUM", "VALUE"], sort="abs_spread_return")
        client.factor_valuations(side="tailwind")
        client.factor_valuation_stocks(factor="VALUE", sort="score")
        client.factor_pairs(factor1="MOMENTUM", factor2="VALUE")
        client.factor_pair_history("MOM/US", "VAL/US", response_mode="compact")
        client.factor_bulk_download(factors=["MOMENTUM"], include="series")
        client.factor_custom({"symbol": "AAPL"}, params={"response_mode": "compact"})
        client.portfolio_attribution({"holdings": [{"symbol": "AAPL", "weight": 1}]}, params={"response_mode": "compact"})
        client.model_factor_analysis({"model": {"id": "draft"}, "holdings": [{"symbol": "AAPL", "weight": 1}]}, params={"response_mode": "compact"})
        client.portfolio_hedge(
            {"holdings": [{"symbol": "AAPL", "weight": 1}], "constraints": {"maxHedges": 1}},
            params={"response_mode": "compact"},
        )

        paths = [url.split("https://api.secapi.ai", 1)[1].split("?", 1)[0] for _method, url, _body in seen]
        self.assertEqual(
            paths,
            [
                "/v1/factors/history/MKT%2FUS",
                "/v1/factors/sparklines",
                "/v1/factors/extreme-moves",
                "/v1/factors/extreme-pairs",
                "/v1/factors/valuations",
                "/v1/factors/valuations/stocks",
                "/v1/factors/pairs",
                "/v1/factors/pair-history/MOM%2FUS/VAL%2FUS",
                "/v1/factors/bulk-download",
                "/v1/factors/custom",
                "/v1/portfolio/attribution",
                "/v1/models/factor-analysis",
                "/v1/portfolio/hedge",
            ],
        )
        self.assertIn("response_mode=compact", seen[0][1])
        self.assertIn("factors=MOMENTUM", seen[1][1])
        self.assertIn("factors=VALUE", seen[1][1])
        self.assertIn("include=series", seen[8][1])
        self.assertIn("response_mode=compact", seen[9][1])
        self.assertIn("response_mode=compact", seen[12][1])
        self.assertEqual([method for method, _url, _body in seen[9:]], ["POST", "POST", "POST", "POST"])
        self.assertNotIn("response_mode", seen[12][2])
        self.assertIn("constraints", seen[12][2])


if __name__ == "__main__":
    unittest.main()
