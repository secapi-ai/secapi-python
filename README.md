# SEC API Python SDK

Use SEC API from Python to retrieve SEC filings, company data, financial statements, ownership data, and more.

## Install

```bash
pip install secapi-client
```

## Make a request

Create an API key in the [SEC API dashboard](https://secapi.ai/signup), then keep it in an environment variable. Do not place API keys in source code or commit them to a repository.

```bash
export SECAPI_API_KEY="secapi_live_..."
```

```python
import os

from secapi_client import SecApiClient

client = SecApiClient(api_key=os.environ["SECAPI_API_KEY"])
filing = client.latest_filing(ticker="AAPL", form="10-K")

print(filing)
```

This requests the most recent Apple 10-K and returns the API response as a Python dictionary. Use the returned filing metadata to select a filing, retrieve a section, or continue with another SEC API workflow.

## Documentation and support

- [Python SDK documentation](https://docs.secapi.ai/python-sdk)
- [Getting started](https://docs.secapi.ai/getting-started)
- [API reference](https://docs.secapi.ai/api-reference)
- [Report an SDK issue](https://github.com/secapi-ai/secapi-python/issues)
- [API status](https://status.secapi.ai)

## Compatibility

Requires Python 3.11 or later. The SDK connects to `https://api.secapi.ai` by default and authenticates API-key requests with `SECAPI_API_KEY`.

## Status

The package version in this release is `1.0.1`. See the [status page](https://status.secapi.ai) for API availability and incident updates.
