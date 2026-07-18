# SEC API Python SDK

`secapi-client` is the Python client for retrieving source-backed SEC filings, filing sections, financial statements, ownership data, and factor data.

## Install and retrieve a filing

```bash
python -m pip install secapi-client
export SECAPI_API_KEY="secapi_..."
```

Create `first_request.py`:

```python
from secapi_client import SecApiClient

client = SecApiClient()
filing = client.agent_latest_filing(ticker="AAPL", form="10-K")

print({
    "accessionNumber": filing.get("accessionNumber"),
    "filingDate": filing.get("filingDate"),
    "filingUrl": filing.get("filingUrl"),
    "requestId": filing.get("requestId"),
})
```

Run `python first_request.py`. It prints the current filing identity and request ID for Apple's latest matching 10-K. Those live values can change when a newer filing is available.

`SecApiClient` sends `SECAPI_API_KEY` as `x-api-key` to `https://api.secapi.ai`. It wraps public REST endpoints; use the [hosted MCP server](https://docs.secapi.ai/mcp-install) separately when your client supports MCP. Keep API keys out of browser code and do not use a machine key as an `Authorization: Bearer` token.

## Compatibility and support

Python 3.11 or newer is required. See the [Python SDK guide](https://docs.secapi.ai/python-sdk) and [API reference](https://docs.secapi.ai/api-reference), check [status](https://status.secapi.ai), or [open an SDK issue](https://github.com/secapi-ai/secapi-python/issues).

`SECAPI_BASE_URL` and `SECAPI_API_BASE_URL` can override the default origin. Failures raise `SecApiError`, which includes status, error code, and request ID when supplied. Preserve filing identifiers and request IDs with derived output.

## License

MIT
