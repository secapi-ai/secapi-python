# SEC API Python SDK

`secapi-client` is the Python client for SEC API filings, statements, ownership data, factor data, and filing sections.

[Documentation](https://docs.secapi.ai) · [Get an API key](https://secapi.ai/signup) · [Support](https://github.com/secapi-ai/secapi-python) · [Status](https://status.secapi.ai)

## Install and make a request

```bash
pip install secapi-client
export SECAPI_API_KEY="secapi_live_..."
```

Create `first_request.py`:

```python
from secapi_client import SecApiClient

client = SecApiClient()
filing = client.agent_latest_filing(ticker="AAPL", form="10-K")

print(filing["accessionNumber"])
print(filing["filingUrl"])
```

Run `python first_request.py`. It prints the latest matching filing's accession number and SEC source URL; both can change after a new filing.

## Common requests

```python
company = client.resolve_entity(ticker="AAPL")
filings = client.search_filings(ticker="AAPL", forms="10-K,10-Q", limit=20)
risk_factors = client.agent_section(ticker="AAPL", form="10-K", section_key="item_1a")
income = client.agent_statement("income_statement", ticker="AAPL", period="annual", limit=3)
```

Flat methods cover the SDK surface. Grouped namespaces including `client.entities`, `client.filings`, `client.sections`, `client.search`, and `client.factors` offer discoverable equivalents for common workflows.

## Factor response modes

Use `response_mode="compact"` when you want the smallest useful payload. Compact catalog responses still include readiness/proof summaries. Set `include="trust"` only when you need the full trust/provenance envelope plus full methodology/materialization/revision/source-rights objects for citations or checks. For catalog/tool-discovery calls, start narrow with `category` and `limit`; the full trust envelope can be larger than a simple picker payload.

## Configuration and compatibility

`SecApiClient()` reads `SECAPI_API_KEY` and optional `SECAPI_BASE_URL` by default. `SECAPI_API_BASE_URL` is an alias. Pass `bearer_token` or set `SECAPI_BEARER_TOKEN` only for signed-in account endpoints; normal data requests use an API key.

Python 3.11 or newer is required. The legacy `OMNI_DATASTREAM_API_KEY`, `OMNI_DATASTREAM_BEARER_TOKEN`, `OMNI_DATASTREAM_BASE_URL`, and `OMNI_DATASTREAM_API_BASE_URL` environment variables remain supported for compatibility.

Failures raise `SecApiError`, which includes status, error code, and request ID. Include the request ID with a [support report](https://github.com/secapi-ai/secapi-python). See the [API documentation](https://docs.secapi.ai) for pagination, retries, and complete endpoint coverage.

## License

MIT
