from __future__ import annotations

import json
import math
import os
import random
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator, Literal, TypeVar
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

#: ``?view=`` response mode. Mirrors the canonical ``ResponseView`` union in
#: SEC API contracts. Agent mode returns a strictly smaller,
#: essentials+citation-pointers shape on supported endpoints.
ResponseView = Literal["default", "compact", "agent"]

SDK_VERSION = "1.0.1"
POSTHOG_CAPTURE_HOST = "https://us.i.posthog.com"
DEFAULT_TIMEOUT_SECONDS = 30.0
SAFE_RETRY_METHODS = {"GET", "HEAD", "OPTIONS"}
RETRYABLE_STATUSES = {408, 429, 502, 503, 504}
NEVER_RETRY_STATUSES = {400, 401, 403, 404, 422}
DEFAULT_RETRY_CONFIG = {
    "max_retries": 3,
    "base_delay_ms": 200,
    "max_delay_ms": 5_000,
    "total_budget_ms": 30_000,
    "circuit_breaker_failure_threshold": 5,
    "circuit_breaker_cooldown_ms": 60_000,
}

T = TypeVar("T")


def _env(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _first_env(*names: str) -> str | None:
    for name in names:
        value = _env(name)
        if value:
            return value
    return None


def _option(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


@dataclass
class SecApiError(Exception):
    status: int
    payload: dict[str, Any]
    retry_after_ms: int | None = None
    headers: dict[str, Any] | None = None

    def __str__(self) -> str:
        request_id = self.request_id
        suffix = f", request_id={request_id}" if request_id else ""
        return f"SecApiError(status={self.status}, code={self.code}, message={self.message}{suffix})"

    @property
    def code(self) -> str | None:
        return _payload_string(self.payload, "code", "errorCode", "error_code") or _nested_error_string(
            self.payload,
            "code",
            "errorCode",
            "error_code",
            "type",
        )

    @property
    def message(self) -> str | None:
        return (
            _payload_string(self.payload, "message", "detail", "title")
            or _nested_error_string(self.payload, "message", "detail", "title")
            or _payload_string(self.payload, "error")
        )

    @property
    def request_id(self) -> str | None:
        return _payload_string(self.payload, "requestId", "request_id") or _header_string(
            self.headers,
            "request-id",
            "x-request-id",
            "x-correlation-id",
        )

    @property
    def status_code(self) -> int:
        return self.status

    @property
    def body(self) -> dict[str, Any]:
        return self.payload

    @property
    def json_body(self) -> dict[str, Any]:
        return self.payload

    @property
    def error_code(self) -> str | None:
        return self.code

    @property
    def requestId(self) -> str | None:
        return self.request_id


def _payload_string(payload: dict[str, Any], *keys: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _nested_error_string(payload: dict[str, Any], *keys: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    return _payload_string(error, *keys) if isinstance(error, dict) else None


def _header_string(headers: dict[str, Any] | None, *names: str) -> str | None:
    if not headers:
        return None
    normalized = {str(key).lower(): value for key, value in headers.items()}
    for name in names:
        value = normalized.get(name.lower())
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


class _ClientCircuitBreaker:
    def __init__(self, failure_threshold: int, cooldown_ms: int) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_ms = cooldown_ms
        self.state = "closed"
        self.consecutive_failures = 0
        self.opened_at = 0.0
        self._lock = threading.RLock()

    def before_request(self, now_ms: float) -> None:
        with self._lock:
            if self.state != "open":
                return
            if now_ms - self.opened_at >= self.cooldown_ms:
                self.state = "half_open"
                return
            raise SecApiError(0, {"code": "client_circuit_open", "message": "SEC API client circuit breaker is open"})

    def record_success(self) -> None:
        with self._lock:
            self.state = "closed"
            self.consecutive_failures = 0
            self.opened_at = 0.0

    def record_failure(self, now_ms: float) -> None:
        with self._lock:
            self.consecutive_failures += 1
            if self.state == "half_open" or self.consecutive_failures >= self.failure_threshold:
                self.state = "open"
                self.opened_at = now_ms

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self.state,
                "consecutive_failures": self.consecutive_failures,
                "opened_at": self.opened_at,
            }


class _ClientNamespace:
    def __init__(self, client: Any, **methods: str) -> None:
        self._client = client
        self._methods = methods

    def __getattr__(self, name: str) -> Any:
        method_name = self._methods.get(name)
        if method_name is None:
            raise AttributeError(f"{type(self).__name__} has no attribute {name!r}")
        return getattr(self._client, method_name)

    def __dir__(self) -> list[str]:
        return sorted(set(super().__dir__()) | set(self._methods))


def _parse_retry_after_ms(value: str | None, now_ms: float) -> int | None:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        seconds = float(value)
        if math.isfinite(seconds) and seconds >= 0:
            return round(seconds * 1000)
    except (ValueError, OverflowError):
        pass
    try:
        from email.utils import parsedate_to_datetime

        parsed = parsedate_to_datetime(value)
        return max(0, round(parsed.timestamp() * 1000 - now_ms))
    except (TypeError, ValueError, OverflowError):
        return None


def _route_template(path: str) -> str:
    segments = []
    for segment in path.split("?")[0].split("/"):
        if len(segment) >= 8 and all(char in "0123456789abcdefABCDEF" for char in segment):
            segments.append(":id")
        elif len(segment) >= 10 and any(char.isdigit() for char in segment) and segment.replace("-", "").isalnum():
            segments.append(":id")
        else:
            segments.append(segment)
    return "/".join(segments)


def _default_page_items(page: dict[str, Any]) -> Iterable[Any]:
    for key in ("data", "items", "results", "sections", "filings"):
        value = page.get(key)
        if isinstance(value, list):
            return value
    return []


def _default_next_cursor(page: dict[str, Any]) -> Any:
    if page.get("hasMore") is False or page.get("has_more") is False:
        return None
    return page.get("nextCursor") if "nextCursor" in page else page.get("next_cursor")


def _normalize_cursor(value: Any) -> str | None:
    if value is None:
        return None
    cursor = str(value).strip()
    return cursor or None


def _positive_int_or_none(value: int | None) -> int | None:
    if value is None:
        return None
    return max(0, int(value))


class SecApiClient:
    def __init__(
        self,
        api_key: str | None = None,
        bearer_token: str | None = None,
        base_url: str | None = None,
        api_version: str = "2026-03-19",
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
        timeout: float | None = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.api_key = _option(api_key) or _first_env("SECAPI_API_KEY", "OMNI_DATASTREAM_API_KEY")
        self.bearer_token = _option(bearer_token) or _first_env("SECAPI_BEARER_TOKEN", "OMNI_DATASTREAM_BEARER_TOKEN")
        resolved_base_url = _option(base_url) or _first_env("SECAPI_BASE_URL", "SECAPI_API_BASE_URL", "OMNI_DATASTREAM_BASE_URL", "OMNI_DATASTREAM_API_BASE_URL")
        self.base_url = (resolved_base_url or "https://api.secapi.ai").rstrip("/")
        self.api_version = api_version
        self.retry = retry
        self.telemetry = telemetry
        self.timeout = float(timeout) if timeout is not None else None
        self._urlopen = urlopen
        self._circuit_breaker = _ClientCircuitBreaker(
            DEFAULT_RETRY_CONFIG["circuit_breaker_failure_threshold"],
            DEFAULT_RETRY_CONFIG["circuit_breaker_cooldown_ms"],
        )
        self._telemetry_distinct_id = f"py-sdk-{id(self):x}-{int(time.time() * 1000):x}"
        self.entities = _ClientNamespace(
            self,
            resolve="resolve_entity",
            search="search_entities",
            paginate="paginate_entities",
        )
        self.filings = _ClientNamespace(
            self,
            search="search_filings",
            paginate="paginate_filings",
            by_accession="filing_by_accession",
            latest="latest_filing",
            agent_latest="agent_latest_filing",
            render_latest="render_latest_filing",
        )
        self.sections = _ClientNamespace(
            self,
            search="search_sections",
            paginate="paginate_sections",
            latest="latest_section",
            agent_latest="agent_section",
            by_accession="filing_section_by_accession",
        )
        self.search = _ClientNamespace(
            self,
            semantic="semantic_search",
            fulltext="search_fulltext",
        )
        self.factors = _ClientNamespace(
            self,
            catalog="factor_catalog",
            returns="factor_returns",
            history="factor_history",
            sparklines="factor_sparklines",
            returns_intraday="factor_returns_intraday",
            dashboard="factor_dashboard",
            regime_performance="factor_regime_performance",
            correlations="factor_correlations",
            screen="factor_screen",
            extreme_moves="factor_extreme_moves",
            extreme_pairs="factor_extreme_pairs",
            valuations="factor_valuations",
            valuation_stocks="factor_valuation_stocks",
            exposures="factor_exposures",
            decomposition="factor_decomposition",
            related_stocks="factor_related_stocks",
            similarity_pack="factor_similarity_pack",
            pairs="factor_pairs",
            pair_history="factor_pair_history",
            bulk_download="factor_bulk_download",
            custom="factor_custom",
        )

    def _headers(self) -> dict[str, str]:
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "secapi-version": self.api_version,
            "user-agent": f"secapi-client/{self.api_version}",
        }
        if self.bearer_token:
            headers["authorization"] = f"Bearer {self.bearer_token}"
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    @property
    def circuit_state(self) -> dict[str, Any]:
        return self._circuit_breaker.snapshot()

    def _request_options_from_params(self, params: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
        params = dict(params or {})
        options: dict[str, Any] = {}
        if "retry" in params:
            options["retry"] = params.pop("retry")
        if "telemetry" in params:
            options["telemetry"] = params.pop("telemetry")
        return params, options

    def _merge_retry_options(self, retry: bool | dict[str, Any] | None) -> tuple[bool, dict[str, Any], bool]:
        global_retry = self.retry
        if retry is False:
            return True, {}, False
        call_options = retry if isinstance(retry, dict) else {}
        unsafe_opt_in = isinstance(retry, dict) and retry.get("enabled") is True
        if global_retry is False and not unsafe_opt_in:
            return True, {}, False
        global_options = global_retry if isinstance(global_retry, dict) else {}
        options = {**global_options, **call_options}
        disabled = options.get("enabled") is False
        return disabled, options, unsafe_opt_in

    def _merge_telemetry_options(self, telemetry: bool | dict[str, Any] | None) -> tuple[bool, dict[str, Any]]:
        global_telemetry = self.telemetry
        if global_telemetry is False or telemetry is False:
            return True, {}
        global_options = global_telemetry if isinstance(global_telemetry, dict) else {}
        call_options = telemetry if isinstance(telemetry, dict) else {}
        disabled = global_options.get("enabled") is False or call_options.get("enabled") is False
        return disabled, {**global_options, **call_options}

    def _request_timeout_seconds(self, remaining_ms: float) -> float | None:
        if self.timeout is None:
            return None
        candidates = []
        candidates.append(self.timeout)
        if math.isfinite(remaining_ms):
            candidates.append(max(0.001, remaining_ms / 1000))
        return min(candidates) if candidates else None

    def _should_retry(self, method: str, error: Exception, retry_disabled: bool, unsafe_opt_in: bool) -> tuple[bool, int | None, str]:
        if retry_disabled:
            return False, None, "disabled"
        if isinstance(error, SecApiError):
            status = error.status
            if status in NEVER_RETRY_STATUSES:
                return False, status, "non_retryable_status"
            if status not in RETRYABLE_STATUSES:
                return False, status, "status"
            if status == 429:
                return True, status, "status"
            if method in SAFE_RETRY_METHODS or unsafe_opt_in:
                return True, status, "status"
            return False, status, "method"
        if method in SAFE_RETRY_METHODS or unsafe_opt_in:
            return True, None, "network"
        return False, None, "method"

    def _retry_delay_ms(self, attempt: int, retry_after_ms: int | None, retry_options: dict[str, Any]) -> int:
        if retry_after_ms is not None:
            return retry_after_ms
        base_delay_ms = int(retry_options.get("base_delay_ms", DEFAULT_RETRY_CONFIG["base_delay_ms"]))
        max_delay_ms = int(retry_options.get("max_delay_ms", DEFAULT_RETRY_CONFIG["max_delay_ms"]))
        random_fn = retry_options.get("random", random.random)
        return int(random_fn() * min(max_delay_ms, base_delay_ms * (2 ** attempt)))

    def _emit_retry_telemetry(
        self,
        *,
        method: str,
        path: str,
        attempt: int,
        max_retries: int,
        delay_ms: int,
        status: int | None,
        reason: str,
        elapsed_ms: float,
        telemetry: bool | dict[str, Any] | None,
    ) -> None:
        disabled, options = self._merge_telemetry_options(telemetry)
        if disabled:
            return
        capture_token = options.get("capture_token")
        host = str(options.get("host", POSTHOG_CAPTURE_HOST)).rstrip("/")
        opener = options.get("opener", urlopen)
        payload = {
            "api_key": capture_token,
            "event": "client_retry_attempt",
            "distinct_id": options.get("distinct_id", self._telemetry_distinct_id),
            "properties": {
                "sdk_language": "py",
                "sdk_version": SDK_VERSION,
                "method": method,
                "route": _route_template(path),
                "server_origin": self.base_url,
                "attempt": attempt,
                "max_retries": max_retries,
                "delay_ms": delay_ms,
                "status": status,
                "reason": reason,
                "elapsed_ms": round(elapsed_ms),
                "$process_person_profile": False,
            },
        }

        def send() -> None:
            data = json.dumps(payload).encode("utf-8")
            request = Request(f"{host}/capture/", data=data, method="POST", headers={"content-type": "application/json"})
            response = None
            try:
                response = opener(request, timeout=float(options.get("timeout", 1.0)))
            except Exception:
                return
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()

        if options.get("sync") is True:
            send()
        else:
            threading.Thread(target=send, daemon=True).start()

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        *,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params, param_options = self._request_options_from_params(params)
        if retry is None:
            retry = param_options.get("retry")
        if telemetry is None:
            telemetry = param_options.get("telemetry")
        method = method.upper()
        retry_disabled, retry_options, unsafe_opt_in = self._merge_retry_options(retry)
        max_retries = max(0, int(retry_options.get("max_retries", DEFAULT_RETRY_CONFIG["max_retries"])))
        total_budget_ms = math.inf if retry_disabled else int(retry_options.get("total_budget_ms", DEFAULT_RETRY_CONFIG["total_budget_ms"]))
        now = retry_options.get("now", lambda: time.time() * 1000)
        sleep = retry_options.get("sleep", lambda delay_ms: time.sleep(delay_ms / 1000))
        started_at = float(now())
        circuit_eligible = not retry_disabled
        if circuit_eligible:
            self._circuit_breaker.before_request(started_at)

        filtered_params = {
            key: value
            for key, value in params.items()
            if value is not None and value != ""
        }
        query = f"?{urlencode(filtered_params, doseq=True)}" if filtered_params else ""
        payload = json.dumps(body).encode("utf-8") if body is not None else None

        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            elapsed_ms = float(now()) - started_at
            remaining_ms = total_budget_ms - elapsed_ms
            if remaining_ms <= 0:
                if circuit_eligible and last_error is not None:
                    self._circuit_breaker.record_failure(float(now()))
                if last_error is not None:
                    raise last_error
                raise SecApiError(0, {"code": "client_retry_budget_exceeded", "message": "SEC API request exceeded retry budget"})

            headers = self._headers()
            idempotency_key = retry_options.get("idempotency_key")
            if idempotency_key:
                headers["Idempotency-Key"] = str(idempotency_key)
            request = Request(f"{self.base_url}{path}{query}", data=payload, method=method, headers=headers)

            try:
                timeout_seconds = self._request_timeout_seconds(remaining_ms)
                response_context = self._urlopen(request) if timeout_seconds is None else self._urlopen(request, timeout=timeout_seconds)
                with response_context as response:
                    if response.status == 204:
                        if circuit_eligible:
                            self._circuit_breaker.record_success()
                        return {}
                    raw = response.read().decode("utf-8")
                    if not raw.strip():
                        if circuit_eligible:
                            self._circuit_breaker.record_success()
                        return {}
                    data = json.loads(raw)
                    if circuit_eligible:
                        self._circuit_breaker.record_success()
                    return data
            except HTTPError as error:
                raw_payload = error.read().decode("utf-8", errors="replace")
                try:
                    error_payload = json.loads(raw_payload)
                except json.JSONDecodeError:
                    error_payload = {"message": raw_payload or error.reason}
                last_error = SecApiError(
                    status=error.code,
                    payload=error_payload,
                    retry_after_ms=_parse_retry_after_ms(error.headers.get("Retry-After"), float(now())),
                    headers=dict(error.headers.items()),
                )
            except (URLError, TimeoutError, OSError) as error:
                last_error = error

            retryable, status, reason = self._should_retry(method, last_error, retry_disabled, unsafe_opt_in)
            if not retryable or attempt >= max_retries:
                if retryable and circuit_eligible:
                    self._circuit_breaker.record_failure(float(now()))
                raise last_error
            delay_ms = self._retry_delay_ms(attempt, last_error.retry_after_ms if isinstance(last_error, SecApiError) and status == 429 else None, retry_options)
            elapsed_after_attempt_ms = float(now()) - started_at
            if elapsed_after_attempt_ms + delay_ms > total_budget_ms:
                if circuit_eligible:
                    self._circuit_breaker.record_failure(float(now()))
                raise last_error
            self._emit_retry_telemetry(
                method=method,
                path=path,
                attempt=attempt + 1,
                max_retries=max_retries,
                delay_ms=delay_ms,
                status=status,
                reason=reason,
                elapsed_ms=elapsed_after_attempt_ms,
                telemetry=telemetry,
            )
            sleep(delay_ms)

        raise last_error or SecApiError(0, {"code": "client_request_failed", "message": "SEC API request failed"})

    def health(
        self,
        *,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request("GET", "/healthz", retry=retry, telemetry=telemetry)

    def me(self) -> dict[str, Any]:
        return self._request("GET", "/v1/me")

    def org(self) -> dict[str, Any]:
        return self._request("GET", "/v1/org")

    def billing(self) -> dict[str, Any]:
        return self._request("GET", "/v1/billing")

    def dashboard_overview(self) -> dict[str, Any]:
        return self._request("GET", "/v1/dashboard/overview")

    def list_api_keys(self) -> dict[str, Any]:
        return self._request("GET", "/v1/api_keys")

    def create_api_key(
        self,
        *,
        label: str | None = None,
        scopes: list[str] | None = None,
        livemode: bool | None = None,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request("POST", "/v1/api_keys", body={"label": label, "scopes": scopes, "livemode": livemode}, retry=retry, telemetry=telemetry)

    def delete_api_key(
        self,
        key_id: str,
        *,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        encoded_key_id = quote(key_id, safe="")
        return self._request("DELETE", f"/v1/api_keys/{encoded_key_id}", retry=retry, telemetry=telemetry)

    def create_agent_bootstrap_token(
        self,
        *,
        label: str | None = None,
        scopes: list[str] | None = None,
        ttl_seconds: int | None = None,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/agent/bootstrap_tokens",
            body={"label": label, "scopes": scopes, "ttlSeconds": ttl_seconds},
            retry=retry,
            telemetry=telemetry,
        )

    def bootstrap_agent(
        self,
        *,
        token: str,
        label: str | None = None,
        scopes: list[str] | None = None,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request("POST", "/v1/agent/bootstrap", body={"token": token, "label": label, "scopes": scopes}, retry=retry, telemetry=telemetry)

    def quote_billing(
        self,
        *,
        plan_key: str | None = None,
        meter_class: str | None = None,
        path: str | None = None,
        method: str | None = None,
        units: int | None = None,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/billing/quote",
            body={"planKey": plan_key, "meterClass": meter_class, "path": path, "method": method, "units": units},
            retry=retry,
            telemetry=telemetry,
        )

    def update_billing_budget(
        self,
        *,
        spend_cap_cents: int | None = None,
        soft_cap_cents: int | None = None,
        approval_threshold_cents: int | None = None,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "PUT",
            "/v1/billing/budget",
            body={
                "spendCapCents": spend_cap_cents,
                "softCapCents": soft_cap_cents,
                "approvalThresholdCents": approval_threshold_cents,
            },
            retry=retry,
            telemetry=telemetry,
        )

    def create_checkout_session(
        self,
        *,
        plan_key: str,
        success_url: str | None = None,
        cancel_url: str | None = None,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request("POST", "/v1/billing/checkout", body={"planKey": plan_key, "successUrl": success_url, "cancelUrl": cancel_url}, retry=retry, telemetry=telemetry)

    def create_billing_portal_session(
        self,
        *,
        return_url: str | None = None,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request("POST", "/v1/billing/portal", body={"returnUrl": return_url}, retry=retry, telemetry=telemetry)

    def usage(self) -> dict[str, Any]:
        return self._request("GET", "/v1/usage")

    def limits(self) -> dict[str, Any]:
        return self._request("GET", "/v1/limits")

    def events(
        self,
        *,
        kind: str | None = None,
        type: str | None = None,
        request_id: str | None = None,
        since: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        return self._request("GET", "/v1/events", params={"kind": kind, "type": type, "requestId": request_id, "since": since, "limit": limit})

    def export_events(
        self,
        *,
        kind: str | None = None,
        type: str | None = None,
        request_id: str | None = None,
        since: str | None = None,
        limit: int | None = None,
        format: str = "json",
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/v1/events/export",
            params={"kind": kind, "type": type, "requestId": request_id, "since": since, "limit": limit, "format": format},
        )

    def request_diagnostics(self, request_id: str) -> dict[str, Any]:
        encoded_request_id = quote(request_id, safe="")
        return self._request("GET", f"/v1/diagnostics/requests/{encoded_request_id}")

    def list_admin_organizations(self, *, q: str | None = None, limit: int | None = None) -> dict[str, Any]:
        return self._request("GET", "/v1/admin/orgs", params={"q": q, "limit": limit})

    def get_admin_organization(self, org_id: str, *, limit: int | None = None) -> dict[str, Any]:
        encoded_org_id = quote(org_id, safe="")
        return self._request("GET", f"/v1/admin/orgs/{encoded_org_id}", params={"limit": limit})

    def get_admin_request_diagnostics(self, org_id: str, request_id: str) -> dict[str, Any]:
        encoded_org_id = quote(org_id, safe="")
        encoded_request_id = quote(request_id, safe="")
        return self._request("GET", f"/v1/admin/orgs/{encoded_org_id}/requests/{encoded_request_id}")

    def get_admin_delivery_summary(
        self,
        org_id: str,
        *,
        since: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        encoded_org_id = quote(org_id, safe="")
        return self._request(
            "GET",
            f"/v1/admin/orgs/{encoded_org_id}/deliveries/summary",
            params={"since": since, "limit": limit},
        )

    def delivery_summary(self, *, since: str | None = None, limit: int | None = None) -> dict[str, Any]:
        return self._request("GET", "/v1/diagnostics/deliveries/summary", params={"since": since, "limit": limit})

    def observability(self) -> dict[str, Any]:
        return self._request("GET", "/v1/observability")

    def export_observability(self, *, limit: int | None = None) -> dict[str, Any]:
        return self._request("GET", "/v1/observability/export", params={"limit": limit})

    def list_webhook_endpoints(self) -> dict[str, Any]:
        return self._request("GET", "/v1/webhook_endpoints")

    def create_webhook_endpoint(
        self,
        *,
        destination_url: str,
        description: str | None = None,
        subscribed_event_types: list[str] | None = None,
        livemode: bool | None = None,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/webhook_endpoints",
            body={
                "destinationUrl": destination_url,
                "description": description,
                "subscribedEventTypes": subscribed_event_types,
                "livemode": livemode,
            },
            retry=retry,
            telemetry=telemetry,
        )

    def rotate_webhook_endpoint_secret(
        self,
        webhook_id: str,
        *,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        encoded_webhook_id = quote(webhook_id, safe="")
        return self._request(
            "POST",
            f"/v1/webhook_endpoints/{encoded_webhook_id}/rotate_secret",
            retry=retry,
            telemetry=telemetry,
        )

    def list_webhook_deliveries(self, webhook_id: str, *, event_id: str | None = None, limit: int | None = None) -> dict[str, Any]:
        encoded_webhook_id = quote(webhook_id, safe="")
        return self._request(
            "GET",
            f"/v1/webhook_endpoints/{encoded_webhook_id}/deliveries",
            params={"eventId": event_id, "limit": limit},
        )

    def replay_webhook_delivery(
        self,
        webhook_id: str,
        delivery_id: str,
        *,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        encoded_webhook_id = quote(webhook_id, safe="")
        encoded_delivery_id = quote(delivery_id, safe="")
        return self._request(
            "POST",
            f"/v1/webhook_endpoints/{encoded_webhook_id}/deliveries/{encoded_delivery_id}/replay",
            retry=retry,
            telemetry=telemetry,
        )

    def list_stream_subscriptions(self) -> dict[str, Any]:
        return self._request("GET", "/v1/stream_subscriptions")

    def create_stream_subscription(
        self,
        *,
        description: str | None = None,
        event_types: list[str] | None = None,
        transport: str | None = None,
        livemode: bool | None = None,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/stream_subscriptions",
            body={
                "description": description,
                "eventTypes": event_types,
                "transport": transport,
                "livemode": livemode,
            },
            retry=retry,
            telemetry=telemetry,
        )

    def create_monitor(
        self,
        *,
        name: str,
        query: str,
        filters: dict[str, Any] | None = None,
        search_mode: str | None = None,
        webhook_url: str | None = None,
        delivery: dict[str, Any] | None = None,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/monitors",
            body={
                "name": name,
                "query": query,
                "filters": filters,
                "searchMode": search_mode,
                "webhookUrl": webhook_url,
                "delivery": delivery,
            },
            retry=retry,
            telemetry=telemetry,
        )

    def list_monitors(self, *, limit: int | None = None) -> dict[str, Any]:
        return self._request("GET", "/v1/monitors", params={"limit": limit})

    def get_monitor(self, monitor_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/monitors/{quote(monitor_id, safe='')}")

    def update_monitor_delivery(
        self,
        monitor_id: str,
        *,
        type: str,
        config: dict[str, Any],
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/monitors/{quote(monitor_id, safe='')}/delivery",
            body={"type": type, "config": config},
            retry=retry,
            telemetry=telemetry,
        )

    def monitor_matches(self, monitor_id: str, *, limit: int | None = None) -> dict[str, Any]:
        return self._request("GET", f"/v1/monitors/{quote(monitor_id, safe='')}/matches", params={"limit": limit})

    def delete_monitor(
        self,
        monitor_id: str,
        *,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request("DELETE", f"/v1/monitors/{quote(monitor_id, safe='')}", retry=retry, telemetry=telemetry)

    def stream_events(self, stream_id: str, *, cursor: str | None = None, type: str | None = None, limit: int | None = None) -> dict[str, Any]:
        encoded_stream_id = quote(stream_id, safe="")
        return self._request(
            "GET",
            f"/v1/stream_subscriptions/{encoded_stream_id}/events",
            params={"cursor": cursor, "type": type, "limit": limit},
        )

    def paginate(
        self,
        fetch_page: Callable[..., dict[str, Any]],
        params: dict[str, Any] | None = None,
        *,
        max_pages: int | None = None,
        max_items: int | None = None,
        get_items: Callable[[dict[str, Any]], Iterable[T]] | None = None,
        get_next_cursor: Callable[[dict[str, Any]], Any] | None = None,
    ) -> Iterator[T]:
        page_params = dict(params or {})
        page_limit = _positive_int_or_none(max_pages)
        item_limit = _positive_int_or_none(max_items)
        if page_limit == 0 or item_limit == 0:
            return

        item_reader = get_items or _default_page_items
        cursor_reader = get_next_cursor or _default_next_cursor
        seen_cursors: set[str] = set()
        initial_cursor = _normalize_cursor(page_params.get("cursor"))
        if initial_cursor:
            seen_cursors.add(initial_cursor)

        yielded = 0
        pages = 0
        while page_limit is None or pages < page_limit:
            page = fetch_page(**page_params)
            pages += 1
            page_item_count = 0
            for item in item_reader(page):
                if item_limit is not None and yielded >= item_limit:
                    return
                page_item_count += 1
                yield item
                yielded += 1
            if item_limit is not None and yielded >= item_limit:
                return

            next_cursor = _normalize_cursor(cursor_reader(page))
            if not next_cursor:
                return
            if next_cursor in seen_cursors:
                raise RuntimeError(f"SEC API pagination cursor repeated: {next_cursor}")
            if page_item_count == 0:
                return
            seen_cursors.add(next_cursor)
            page_params = {**page_params, "cursor": next_cursor}

    def resolve_entity(self, *, ticker: str | None = None, cik: str | None = None, name: str | None = None) -> dict[str, Any]:
        return self._request("GET", "/v1/entities/resolve", params={"ticker": ticker, "cik": cik, "name": name})

    def search_entities(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/entities", params=params)

    def paginate_entities(
        self,
        *,
        max_pages: int | None = None,
        max_items: int | None = None,
        get_items: Callable[[dict[str, Any]], Iterable[T]] | None = None,
        get_next_cursor: Callable[[dict[str, Any]], Any] | None = None,
        **params: Any,
    ) -> Iterator[T]:
        return self.paginate(
            self.search_entities,
            params,
            max_pages=max_pages,
            max_items=max_items,
            get_items=get_items,
            get_next_cursor=get_next_cursor,
        )

    def search_filings(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/filings", params=params)

    def paginate_filings(
        self,
        *,
        max_pages: int | None = None,
        max_items: int | None = None,
        get_items: Callable[[dict[str, Any]], Iterable[T]] | None = None,
        get_next_cursor: Callable[[dict[str, Any]], Any] | None = None,
        **params: Any,
    ) -> Iterator[T]:
        return self.paginate(
            self.search_filings,
            params,
            max_pages=max_pages,
            max_items=max_items,
            get_items=get_items,
            get_next_cursor=get_next_cursor,
        )

    def filing_by_accession(self, accession_number: str, **params: Any) -> dict[str, Any]:
        encoded_accession_number = quote(accession_number, safe="")
        return self._request("GET", f"/v1/filings/{encoded_accession_number}", params=params)

    def latest_filing(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/filings/latest", params=params)

    def render_latest_filing(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/filings/latest/render", params=params)

    def latest_section(self, section_key: str, **params: Any) -> dict[str, Any]:
        encoded_section_key = quote(section_key, safe="")
        return self._request("GET", f"/v1/filings/latest/sections/{encoded_section_key}", params=params)

    def filing_section_by_accession(self, accession_number: str, section_key: str, **params: Any) -> dict[str, Any]:
        encoded_accession_number = quote(accession_number, safe="")
        encoded_section_key = quote(section_key, safe="")
        return self._request("GET", f"/v1/filings/{encoded_accession_number}/sections/{encoded_section_key}", params=params)

    def search_sections(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/sections/search", params=params)

    def paginate_sections(
        self,
        *,
        max_pages: int | None = None,
        max_items: int | None = None,
        get_items: Callable[[dict[str, Any]], Iterable[T]] | None = None,
        get_next_cursor: Callable[[dict[str, Any]], Any] | None = None,
        **params: Any,
    ) -> Iterator[T]:
        return self.paginate(
            self.search_sections,
            params,
            max_pages=max_pages,
            max_items=max_items,
            get_items=get_items,
            get_next_cursor=get_next_cursor,
        )

    def semantic_search(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/search/semantic", params=params)

    def search_fulltext(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/search/fulltext", params=params)

    def offerings(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/offerings", params=params)

    def market_calendar(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/market/calendar", params=params)

    def market_snapshots(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/market/snapshots", params=params)

    def market_bars(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/market/bars", params=params)

    def market_corporate_actions(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/market/corporate-actions", params=params)

    def market_reference(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/market/reference", params=params)

    def market_estimates(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/market/estimates", params=params)

    def market_earnings_calendar(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/market/earnings-calendar", params=params)

    def news_stories(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/news/stories", params=params)

    def macro_search(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/macro/search", params=params)

    def macro_indicators(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/macro/indicators", params=params)

    def macro_releases(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/macro/releases", params=params)

    def macro_calendar(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/macro/calendar", params=params)

    def macro_forecasts(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/macro/forecasts", params=params)

    def macro_high_signal_pack(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/macro/high-signal-pack", params=params)

    def macro_regimes(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/macro/regimes", params=params)

    def macro_credit_ratings(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/macro/credit-ratings", params=params)

    def macro_credit_rating(self, country: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/macro/credit-ratings/{quote(country, safe='')}")

    def factor_catalog(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/factors/catalog", params=params)

    def factor_returns(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/factors/returns", params=params)

    def factor_history(self, factor_key: str, **params: Any) -> dict[str, Any]:
        return self._request("GET", f"/v1/factors/history/{quote(factor_key, safe='')}", params=params)

    def factor_sparklines(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/factors/sparklines", params=params)

    def factor_returns_intraday(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/factors/returns/intraday", params=params)

    def factor_dashboard(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/factors/dashboard", params=params)

    def factor_regime_performance(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/factors/regime-performance", params=params)

    def factor_correlations(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/factors/correlations", params=params)

    def factor_screen(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/factors/screen", params=params)

    def factor_extreme_moves(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/factors/extreme-moves", params=params)

    def factor_extreme_pairs(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/factors/extreme-pairs", params=params)

    def factor_valuations(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/factors/valuations", params=params)

    def factor_valuation_stocks(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/factors/valuations/stocks", params=params)

    def factor_exposures(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/factors/exposures", params=params)

    def stock_loadings(self, ticker: str, **params: Any) -> dict[str, Any]:
        encoded_ticker = quote(ticker, safe="")
        return self._request("GET", f"/v1/stocks/{encoded_ticker}/loadings", params=params)

    def factor_decomposition(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/factors/decomposition", params=params)

    def factor_related_stocks(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/factors/related-stocks", params=params)

    def factor_similarity_pack(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/factors/similarity-pack", params=params)

    def factor_pairs(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/factors/pairs", params=params)

    def factor_pair_history(self, f1: str, f2: str, **params: Any) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/v1/factors/pair-history/{quote(f1, safe='')}/{quote(f2, safe='')}",
            params=params,
        )

    def factor_bulk_download(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/factors/bulk-download", params=params)

    def factor_custom(
        self,
        body: dict[str, Any],
        params: dict[str, Any] | None = None,
        *,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request("POST", "/v1/factors/custom", params=params, body=body, retry=retry, telemetry=telemetry)

    def portfolio_analyze(
        self,
        body: dict[str, Any],
        params: dict[str, Any] | None = None,
        *,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request("POST", "/v1/portfolio/analyze", params=params, body=body, retry=retry, telemetry=telemetry)

    def portfolio_attribution(
        self,
        body: dict[str, Any],
        params: dict[str, Any] | None = None,
        *,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request("POST", "/v1/portfolio/attribution", params=params, body=body, retry=retry, telemetry=telemetry)

    def model_portfolio_factor_view(self, portfolio_id: str, **params: Any) -> dict[str, Any]:
        return self._request("GET", f"/v1/model-portfolios/{quote(portfolio_id, safe='')}/factor-view", params=params)

    def model_factor_analysis(
        self,
        body: dict[str, Any],
        params: dict[str, Any] | None = None,
        *,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request("POST", "/v1/models/factor-analysis", params=params, body=body, retry=retry, telemetry=telemetry)

    def portfolio_optimize(
        self,
        body: dict[str, Any],
        params: dict[str, Any] | None = None,
        *,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request("POST", "/v1/portfolio/optimize", params=params, body=body, retry=retry, telemetry=telemetry)

    def portfolio_hedge(
        self,
        body: dict[str, Any],
        params: dict[str, Any] | None = None,
        *,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request("POST", "/v1/portfolio/hedge", params=params, body=body, retry=retry, telemetry=telemetry)

    def portfolio_stress_test(
        self,
        body: dict[str, Any],
        params: dict[str, Any] | None = None,
        *,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request("POST", "/v1/portfolio/stress-test", params=params, body=body, retry=retry, telemetry=telemetry)

    def strategy_factor_rotation(
        self,
        body: dict[str, Any] | None = None,
        *,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request("POST", "/v1/strategies/factor-rotation", body=body or {}, retry=retry, telemetry=telemetry)

    def strategy_regime_screen(
        self,
        body: dict[str, Any] | None = None,
        *,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request("POST", "/v1/strategies/regime-screen", body=body or {}, retry=retry, telemetry=telemetry)

    def intelligence_security(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/intelligence/security", params=params)

    def intelligence_company(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/intelligence/company", params=params)

    def intelligence_earnings_preview(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/intelligence/earnings-preview", params=params)

    def intelligence_country_report(
        self,
        body: dict[str, Any] | None = None,
        *,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request("POST", "/v1/intelligence/country-report", body=body or {}, retry=retry, telemetry=telemetry)

    def intelligence_portfolio(
        self,
        body: dict[str, Any],
        *,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request("POST", "/v1/intelligence/portfolio", body=body, retry=retry, telemetry=telemetry)

    def intelligence_watchlist(
        self,
        body: dict[str, Any],
        *,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
        **params: Any,
    ) -> dict[str, Any]:
        return self._request("POST", "/v1/intelligence/watchlist", params=params, body=body, retry=retry, telemetry=telemetry)

    def intelligence_query(
        self,
        body: dict[str, Any],
        *,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request("POST", "/v1/intelligence/query", body=body, retry=retry, telemetry=telemetry)

    def intelligence_footnotes_query(
        self,
        body: dict[str, Any],
        *,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request("POST", "/v1/intelligence/footnotes/query", body=body, retry=retry, telemetry=telemetry)

    def market_indices(self, *, include_inventory: bool | None = None) -> dict[str, Any]:
        return self._request("GET", "/v1/market/indices", params={"include_inventory": include_inventory})

    def index_constituents(self, *, index: str | None = None, index_code: str | None = None, cursor: str | None = None, limit: int | None = None) -> dict[str, Any]:
        return self._request(
            "GET",
            "/v1/market/indices/constituents",
            params={"index": index, "index_code": index_code, "cursor": cursor, "limit": limit},
        )

    def volatility_signal(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/signals/volatility", params=params)

    def facts(self, *, tag: str, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/facts", params={"tag": tag, **params})

    def statements(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/statements", params=params)

    def all_statements(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/statements/all", params=params)

    def statement_by_key(self, statement_key: str, **params: Any) -> dict[str, Any]:
        encoded_statement_key = quote(statement_key, safe="")
        return self._request("GET", f"/v1/statements/{encoded_statement_key}", params=params)

    def company_income_statements(
        self,
        *,
        ticker: str,
        period: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        return self._request("GET", "/v1/companies/income-statements", params={"ticker": ticker, "period": period, "limit": limit})

    def company_balance_sheets(
        self,
        *,
        ticker: str,
        period: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        return self._request("GET", "/v1/companies/balance-sheets", params={"ticker": ticker, "period": period, "limit": limit})

    def company_cash_flow_statements(
        self,
        *,
        ticker: str,
        period: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        return self._request("GET", "/v1/companies/cash-flow-statements", params={"ticker": ticker, "period": period, "limit": limit})

    def company_financials(
        self,
        *,
        ticker: str,
        period: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        return self._request("GET", "/v1/companies/financials", params={"ticker": ticker, "period": period, "limit": limit})

    def company_ratios(
        self,
        *,
        ticker: str,
        period: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        return self._request("GET", "/v1/companies/ratios", params={"ticker": ticker, "period": period, "limit": limit})

    def company_resolve(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/companies/resolve", params=params)

    def company_search(self, *, q: str, limit: int | None = None) -> dict[str, Any]:
        return self._request("GET", "/v1/companies/search", params={"q": q, "limit": limit})

    def list_13f_filings(
        self,
        *,
        cik: str,
        limit: int | None = None,
        since: str | None = None,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """List 13F filings for a CIK.

        Pairs with `latest_13f` (which returns the *holdings* of one
        specific filing) — this returns the *list* of filings available
        for a CIK so callers can pick a specific (reportDate, filingDate)
        before fetching holdings. Useful for any consumer that wants to
        iterate over a filer's quarterly history or detect newly-landed
        filings via the `since` filter.

        Args:
            cik: 10-digit zero-padded CIK (e.g. "0001067983" for Berkshire).
            limit: Max filings to return (server default applies if None).
            since: Optional ISO-8601 timestamp; when set, returns only
                filings accepted by SEC at or after this timestamp.
                Supports incremental polling for newsletters/alerts
                consumers without scanning the full history each tick.

                **Server-side pairing:** the `since=` filter is honoured
                by datastream-api as of the release containing
                omni-datastream PR #539 (paired with this SDK PR).
                Older servers silently ignore unknown query parameters
                and return the full unfiltered history, so callers
                should always client-side dedupe by `accessionNumber`
                if they need strict incremental semantics during the
                rollout window.

        Returns:
            Raw JSON envelope: `{"object": "list", "data": [{...}], ...}`.
        """
        return self._request(
            "GET",
            "/v1/owners/13f/filings",
            params={"cik": cik, "limit": limit, "since": since},
            retry=retry,
            telemetry=telemetry,
        )

    def latest_13f(
        self,
        *,
        cik: str,
        report_date: str | None = None,
        filing_date: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/v1/owners/13f",
            params={
                "cik": cik,
                "reportDate": report_date,
                "filingDate": filing_date,
                "limit": limit,
            },
        )

    def compare_13f(
        self,
        *,
        cik: str,
        limit: int | None = None,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request("POST", "/v1/owners/13f/compare", body={"cik": cik, "limit": limit}, retry=retry, telemetry=telemetry)

    def insiders(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/insiders", params=params)

    def compensation(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/compensation", params=params)

    def compare_compensation(
        self,
        *,
        ticker: str | None = None,
        cik: str | None = None,
        limit: int | None = None,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request("POST", "/v1/compensation/compare", body={"ticker": ticker, "cik": cik, "limit": limit}, retry=retry, telemetry=telemetry)

    def create_artifact(
        self,
        body: dict[str, Any],
        *,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request("POST", "/v1/artifacts", body=body, retry=retry, telemetry=telemetry)

    def list_artifacts(self, *, kind: str | None = None, status: str | None = None, limit: int | None = None) -> dict[str, Any]:
        return self._request("GET", "/v1/artifacts", params={"kind": kind, "status": status, "limit": limit})

    def artifact_summary(self) -> dict[str, Any]:
        return self._request("GET", "/v1/artifacts/summary")

    def get_artifact(self, artifact_id: str) -> dict[str, Any]:
        encoded_artifact_id = quote(artifact_id, safe="")
        return self._request("GET", f"/v1/artifacts/{encoded_artifact_id}")

    def artifact_manifest(self, artifact_id: str) -> dict[str, Any]:
        encoded_artifact_id = quote(artifact_id, safe="")
        return self._request("GET", f"/v1/artifacts/{encoded_artifact_id}/manifest")

    def export_artifact(self, artifact_id: str, *, format: str = "json") -> dict[str, Any]:
        encoded_artifact_id = quote(artifact_id, safe="")
        return self._request("GET", f"/v1/artifacts/{encoded_artifact_id}/export", params={"format": format})

    def download_artifact(self, artifact_id: str) -> dict[str, Any]:
        encoded_artifact_id = quote(artifact_id, safe="")
        return self._request("GET", f"/v1/artifacts/{encoded_artifact_id}/download")

    def reconcile_artifact(
        self,
        artifact_id: str,
        *,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        encoded_artifact_id = quote(artifact_id, safe="")
        return self._request(
            "POST",
            f"/v1/artifacts/{encoded_artifact_id}/reconcile",
            retry=retry,
            telemetry=telemetry,
        )

    def analytics_query(
        self,
        body: dict[str, Any],
        *,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request("POST", "/v1/analytics/query", body=body, retry=retry, telemetry=telemetry)

    def list_traces(self, *, ids: str | list[str]) -> dict[str, Any]:
        joined = ",".join(ids) if isinstance(ids, list) else ids
        return self._request("GET", "/v1/traces", params={"ids": joined})

    def get_trace(self, trace_id: str) -> dict[str, Any]:
        encoded_trace_id = quote(trace_id, safe="")
        return self._request("GET", f"/v1/traces/{encoded_trace_id}")

    def segmented_revenues(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/statements/segmented-revenues", params=params)

    def segmented_facts(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/statements/segmented-facts", params=params)

    def pension_benefit_schedule(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/filings/pension-benefit-schedule", params=params)

    def share_float(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/statements/share-float", params=params)

    def board_composition(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/board", params=params)

    def nport_holdings(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/funds/nport/holdings", params=params)

    def latest_risk_categories(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/filings/latest/risk-categories", params=params)

    def beneficial_ownership_reports(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/owners/13d-13g", params=params)

    def institutional_ownership_extract(self, *, cik: str, year: int, quarter: int, limit: int | None = None) -> dict[str, Any]:
        return self._request("GET", "/v1/owners/institutional/extract", params={"cik": cik, "year": year, "quarter": quarter, "limit": limit})

    def institutional_holders_by_ticker(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/owners/institutional/ticker", params=params)

    def ma_events(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/events/ma", params=params)

    def enforcement_actions(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/events/enforcement", params=params)

    def voting_results_events(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/events/voting-results", params=params)

    # Dilution endpoints (OMNI-3091). All accept ?view=agent except
    # dilution_coverage, whose route returns a small rollup with no agent shape.
    def dilution_events(self, **params: Any) -> dict[str, Any]:
        # The route's parseQueryBool only matches lowercase "true"/"false"; Python
        # bools serialize as "True"/"False" via urlencode, so coerce here.
        if "is_atm" in params and isinstance(params["is_atm"], bool):
            params["is_atm"] = "true" if params["is_atm"] else "false"
        return self._request("GET", "/v1/dilution/events", params=params)

    def dilution_event_detail(self, event_id: str, **params: Any) -> dict[str, Any]:
        return self._request("GET", f"/v1/dilution/events/{quote(event_id, safe='')}", params=params)

    def dilution_warrants(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/dilution/warrants", params=params)

    def dilution_convertibles(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/dilution/convertibles", params=params)

    def dilution_rofr(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/dilution/rofr", params=params)

    def dilution_lockups(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/dilution/lockups", params=params)

    def dilution_cash_position(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/dilution/cash-position", params=params)

    def dilution_corporate_actions(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/dilution/corporate-actions", params=params)

    def dilution_nasdaq_compliance(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/dilution/nasdaq-compliance", params=params)

    def dilution_ratings(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/dilution/ratings", params=params)

    def dilution_reverse_splits(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/dilution/reverse-splits", params=params)

    def dilution_score(self, *, ticker: str, view: ResponseView | None = None) -> dict[str, Any]:
        return self._request("GET", "/v1/dilution/score", params={"ticker": ticker, "view": view})

    def dilution_share_float_history(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/dilution/share-float-history", params=params)

    def dilution_coverage(self, *, ticker: str | None = None) -> dict[str, Any]:
        return self._request("GET", "/v1/dilution/coverage", params={"ticker": ticker})

    def form_144_filings(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/forms/144", params=params)

    def company_subsidiaries(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/companies/subsidiaries", params=params)

    def earnings_transcripts(self, **params: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/earnings/transcripts", params=params)

    def mcp_info(
        self,
        *,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request("GET", "/mcp", retry=retry, telemetry=telemetry)

    def mcp(
        self,
        request: dict[str, Any],
        *,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request("POST", "/mcp", body=request, retry=retry, telemetry=telemetry)

    def call_mcp_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        id: str | int | None = None,
        retry: bool | dict[str, Any] | None = None,
        telemetry: bool | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.mcp(
            {
                "jsonrpc": "2.0",
                "id": id if id is not None else f"{name}-{int(time.time() * 1000)}",
                "method": "tools/call",
                "params": {
                    "name": name,
                    "arguments": arguments or {},
                },
            },
            retry=retry,
            telemetry=telemetry,
        )

    def agent_latest_filing(self, **params: Any) -> dict[str, Any]:
        return self.latest_filing(**{**params, "view": "agent"})

    def agent_section(self, section_key: str, **params: Any) -> dict[str, Any]:
        return self.latest_section(section_key, **{"mode": "compact", **params})

    def agent_statement(self, statement_key: str, **params: Any) -> dict[str, Any]:
        return self.statement_by_key(statement_key, **{**params, "view": "agent"})

    def agent_institutional_holders(self, **params: Any) -> dict[str, Any]:
        return self.institutional_holders_by_ticker(**{**params, "view": "agent"})

    def agent_form_144(self, **params: Any) -> dict[str, Any]:
        return self.form_144_filings(**{**params, "view": "agent"})


OmniDatastreamClient = SecApiClient
OmniDatastreamError = SecApiError
