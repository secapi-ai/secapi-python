# SEC API Python SDK

`secapi-client` is the Python client for SEC API filings, filing sections, financial statements, ownership data, and factor data.

[Documentation](https://docs.secapi.ai) · [Get an API key](https://secapi.ai/signup) · [Support](https://github.com/secapi-ai/secapi-python/issues) · [Status](https://status.secapi.ai)

## Install

```bash
pip install secapi-client
```

## Set your API key

Create an API key in the [SEC API dashboard](https://secapi.ai/signup), then set it in your shell:

```bash
export SECAPI_API_KEY="secapi_live_..."
```

## Make a request

Create `first_request.py`:

```python
from secapi_client import SecApiClient

client = SecApiClient()
filing = client.agent_latest_filing(ticker="AAPL", form="10-K")

print(filing["accessionNumber"])
print(filing["filingUrl"])
```

Run `python first_request.py`. It prints the accession number and SEC source URL for Apple's latest matching 10-K. Those values change when a newer filing is available.

## Configuration and compatibility

`SecApiClient()` reads `SECAPI_API_KEY` and the optional `SECAPI_BASE_URL` from the environment. `SECAPI_API_BASE_URL` is an alias. Pass `bearer_token` or set `SECAPI_BEARER_TOKEN` only for signed-in account endpoints; standard data requests use an API key.

Python 3.11 or newer is required. The legacy `OMNI_DATASTREAM_API_KEY`, `OMNI_DATASTREAM_BEARER_TOKEN`, `OMNI_DATASTREAM_BASE_URL`, and `OMNI_DATASTREAM_API_BASE_URL` environment variables remain supported.

Failures raise `SecApiError`, which includes the status, error code, and request ID. Include the request ID when opening a [support issue](https://github.com/secapi-ai/secapi-python/issues).

See the [API documentation](https://docs.secapi.ai) for endpoint coverage, pagination, and retry behavior.

## License

MIT
