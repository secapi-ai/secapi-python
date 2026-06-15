# SEC API Python SDK

Python SDK for [SEC API](https://secapi.ai/developers) -- factor data, SEC filings, financial statements, ownership data, and more.

## Installation

```bash
pip install secapi-client
```

## Configuration

```python
from secapi_client import SecApiClient

client = SecApiClient(
    api_key="ods_test_...",
    # Optional: override base URL (defaults to https://api.secapi.ai)
    # base_url="http://127.0.0.1:8787",
)
```

You can also authenticate with a Bearer token:

```python
client = SecApiClient(bearer_token="your-bearer-token")
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `SECAPI_API_KEY` | Your SEC API key (starts with `ods_`) |

### Configuration Options

| Parameter | Default | Description |
|-----------|---------|-------------|
| `api_key` | `None` | API key authentication |
| `bearer_token` | `None` | Bearer token authentication |
| `base_url` | `https://api.secapi.ai` | API base URL |
| `api_version` | `2026-03-19` | API version header |
| `retry` | `None` | Retry configuration, or `False` to disable SDK retries |
| `telemetry` | `None` | Retry telemetry configuration, or `False` to opt out |

## Reliability

The SDK retries transient failures with exponential backoff and jitter. Defaults:

- Auto-retried by default: `GET`, `HEAD`, `OPTIONS`
- Opt-in required: `POST`, `PUT`, `PATCH`, `DELETE`, MCP `tools/call`
- Always retried regardless of method: `429` rate limits, with `Retry-After` honored
- Retryable failures: network errors, `408`, `429`, `502`, `503`, `504`
- Never retried: `400`, `401`, `403`, `404`, `422`
- Backoff: base `200ms`, max `5s`, max retries `3`, total budget `30s`
- Circuit breaker: opens after 5 consecutive retryable failures, cools down for 60s

Disable retries globally if you already wrap the SDK with your own retry layer:

```python
client = SecApiClient(
    api_key="ods_test_...",
    retry=False,
)
```

Per-call overrides are supported:

```python
filing = client.latest_filing(ticker="AAPL", form="10-K", retry=False)

artifact = client.create_artifact(
    {"kind": "audit", "payload": {"ticker": "AAPL"}},
    retry={"enabled": True, "idempotency_key": "artifact-aapl-audit-2026-05-01"},
)
```

Only opt into retries for mutating requests when the operation is idempotent from your application's point of view. Provide an idempotency key so ambiguous network failures can be correlated safely.

Retry telemetry emits anonymous `client_retry_attempt` events to SEC API's telemetry project. Set `telemetry=False` globally or per call to opt out.

## Quickstart

```python
import os
from secapi_client import SecApiClient

api_key = os.environ["SECAPI_API_KEY"]
client = SecApiClient(api_key=api_key)

# Resolve a company entity
entity = client.resolve_entity(ticker="AAPL")
print(entity)

# Get the latest 10-K filing
filing = client.latest_filing(ticker="AAPL", form="10-K")
print(filing)

# Same workflow in the compact agent response shape
agent_filing = client.agent_latest_filing(ticker="AAPL", form="10-K")
print(agent_filing)

# Extract a specific section
section = client.latest_section(
    section_key="item_1a",
    ticker="AAPL",
    form="10-K",
    mode="compact",
)
print(section)
```

## Common Use Cases

### Factor Data and Portfolio Workflows

Use `response_mode="compact"` when you are feeding an agent, LLM, notebook, or UI card and want the smallest useful payload. Add `include="trust"` when you need freshness, methodology, and materialization metadata for citations or launch checks.

```python
# Factor catalog for picker UIs and agent tool discovery
catalog = client.factor_catalog(
    category="style",
    response_mode="compact",
    include="trust",
)

# 1D through MAX style return history for charts and tables
value_history = client.factor_history(
    "VALUE",
    range="1y",
    response_mode="compact",
    include="trust,series",
)

# Factor opportunity screen for valuation-led workflows
valuations = client.factor_valuations(
    keys="VALUE,QUALITY,MOMENTUM",
    side="all",
    sort="opportunity_score",
    response_mode="compact",
    include="trust",
    limit=25,
)

# Extreme moves and pairs for dashboard surfaces
dashboard = client.factor_dashboard(
    country="US",
    category="style",
    ticker="AAPL",
    response_mode="compact",
)
extreme_moves = client.factor_extreme_moves(
    category="style",
    window="1d",
    min_z_score=2,
    response_mode="compact",
)
extreme_pairs = client.factor_extreme_pairs(
    category="style",
    window="1m",
    min_z_score=1,
    response_mode="compact",
)
```

Portfolio and model workflows use `POST` because they carry holdings or model payloads. Keep retries off by default unless your request is idempotent and you provide an idempotency key.

```python
holdings = [
    {"symbol": "AAPL", "weight": 0.4},
    {"symbol": "MSFT", "weight": 0.35},
    {"symbol": "NVDA", "weight": 0.25},
]

attribution = client.portfolio_attribution(
    {"holdings": holdings, "window": "1y", "frequency": "monthly"},
    params={"response_mode": "compact", "include": "trust"},
)

hedge = client.portfolio_hedge(
    {
        "holdings": holdings,
        "objective": "factor_neutral",
        "constraints": {"maxHedges": 5},
    },
    params={"response_mode": "compact", "include": "trust"},
)

optimized = client.portfolio_optimize(
    {
        "holdings": holdings,
        "objective": "regime_aware",
        "constraints": {"longOnly": True, "maxPositionWeight": 0.35},
    },
    params={"response_mode": "compact", "include": "trust"},
)

model_factor_analysis = client.model_factor_analysis(
    {
        "model": {"id": "growth-core", "label": "Growth Core"},
        "holdings": holdings,
        "include": {"attribution": True, "hedge": True, "optimizer": True},
    },
    params={"response_mode": "compact", "include": "trust"},
)
```

### Financial Statements

```python
# XBRL facts
facts = client.facts(ticker="AAPL", tag="Assets", taxonomy="us-gaap", limit=5)

# Full financial statements
statements = client.all_statements(ticker="AAPL", period="annual", limit=3)

# Agent-mode statement rows keep compact source metadata for citations
agent_income = client.agent_statement(
    "income_statement",
    ticker="AAPL",
    period="annual",
    limit=3,
)
```

### Ownership and Institutional Holdings

```python
# Latest 13F filing (institutional holdings)
holdings = client.latest_13f(cik="0001067983", limit=10)

# Issuer-level institutional holders, agent-mode by default
holders = client.agent_institutional_holders(ticker="NVDA", limit=10)

# Form 144 proposed sale filings, agent-mode by default
form144 = client.agent_form_144(ticker="NVDA", limit=10)
```

### Market Data

```python
# Market calendar
calendar = client.market_calendar(market="XNYS", duration=3)

# Volatility signal
vol = client.volatility_signal(ticker="AAPL")
```

### Offerings and M&A

```python
# IPO and offering filings
offerings = client.offerings(forms="S-1,424B4", limit=3)
```

### Diagnostics

```python
# Artifact summary (data freshness)
summary = client.artifact_summary()

# System observability (requires admin:operator)
operator_client = SecApiClient(api_key=os.environ["SECAPI_OPERATOR_API_KEY"])
obs = operator_client.observability()
```

## Error Handling

```python
from secapi_client import SecApiClient, SecApiError

client = SecApiClient(api_key="ods_test_...")

try:
    result = client.resolve_entity(ticker="INVALID")
except SecApiError as e:
    print(f"Status: {e.status}")
    print(f"Payload: {e.payload}")
```

## Scope

The Python SDK covers the full REST surface including:

- Entity resolution and search
- Filing retrieval and section extraction
- XBRL facts and financial statements
- Factor catalog, returns, history, valuations, exposures, decomposition, pairs, and custom discovery
- Portfolio factor attribution, hedging, optimization, stress testing, and model factor analysis
- Offerings, market calendar, and volatility signals
- Ownership, insiders, and compensation data
- Institutional holdings (13F)
- Enforcement actions and M&A events
- Artifacts, diagnostics, and observability
- Events, streams, and webhooks

## MCP (Model Context Protocol)

MCP tool calls use HTTP `POST`, so they are not retried on `502`/`503` by default. Opt in per call only when the tool is read-only or otherwise idempotent:

```python
result = client.call_mcp_tool(
    "sections.get",
    {"ticker": "AAPL", "form": "10-K", "sectionKey": "item_1a", "mode": "compact"},
    id="aapl-risk-factors",
    retry={"enabled": True, "idempotency_key": "mcp-sections-get-aapl-item-1a"},
)
```

The convenience `call_mcp_tool(name, arguments, ...)` helper uses the same `POST /mcp` transport. Use per-call retry opt-in only for read-only tools such as `entities.resolve`, `filings.latest`, `sections.get`, `statements.get`, `owners.institutional_holders`, and `forms.list_144`.

## Links

- [API Documentation](https://docs.secapi.ai)
- [Developer Portal](https://secapi.ai/developers)
- [GitHub Repository](https://github.com/secapi-ai/secapi-python)
