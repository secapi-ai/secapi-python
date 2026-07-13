# SEC API Python SDK

Retrieve source-linked SEC filings and company data from Python.

## Install

```bash
python -m pip install secapi-client
```

## Get a cited filing

Create an API key in the [SEC API dashboard](https://secapi.ai/signup) and export it. `SecApiClient` reads `SECAPI_API_KEY` and sends it as the `x-api-key` request header.

```bash
export SECAPI_API_KEY="secapi_live_..."
```

```python
from secapi_client import SecApiClient

client = SecApiClient()
filing = client.agent_latest_filing(ticker="AAPL", form="10-K")

print(
    {
        "accessionNumber": filing.get("accessionNumber"),
        "filingDate": filing.get("filingDate"),
        "filingUrl": filing.get("filingUrl"),
        "requestId": filing.get("requestId"),
    }
)
```

This requests the latest Apple 10-K and prints its filing identity, SEC source URL, and request identifier. `agent_latest_filing` uses the compact `view=agent` response: it includes the filing URL but does not include the full provenance, freshness, or materialization metadata. Use `client.latest_filing(ticker="AAPL", form="10-K")` when your workflow needs the default response shape.

## Documentation and support

- [Python SDK documentation](https://docs.secapi.ai/python-sdk)
- [Latest filing API reference](https://docs.secapi.ai/api-reference/filings/get-v1-filings-latest)
- [Report an SDK issue](https://github.com/secapi-ai/secapi-python/issues)
- [API status](https://status.secapi.ai)

## Compatibility

Requires Python 3.11 or later. The client connects to `https://api.secapi.ai` by default.
