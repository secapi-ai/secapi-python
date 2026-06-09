import os

from secapi_client import SecApiClient


base_url = (
    os.environ.get("SECAPI_BASE_URL")
    or os.environ.get("SECAPI_API_BASE_URL")
    or "https://api.secapi.ai"
)
client = SecApiClient(
    api_key=os.environ["SECAPI_API_KEY"],
    base_url=base_url,
)

print(client.health())
print(client.me())
print(client.org())
print(client.resolve_entity(ticker="AAPL"))
print(client.latest_filing(ticker="AAPL", form="10-K"))
print(client.search_sections(query="risk factors", ticker="AAPL", limit=3))
print(client.facts(ticker="AAPL", tag="Assets", taxonomy="us-gaap", limit=3))
print(client.all_statements(ticker="AAPL", period="annual", limit=3))
print(client.offerings(forms="S-1,424B4", limit=3))
print(client.market_calendar(market="XNYS", duration=3))
print(client.volatility_signal(ticker="AAPL"))
print(client.latest_13f(cik="0001067983", limit=5))
print(client.insiders(ticker="AAPL", limit=5))
if os.environ.get("SECAPI_OPERATOR_API_KEY"):
    operator_client = SecApiClient(api_key=os.environ["SECAPI_OPERATOR_API_KEY"], base_url=base_url)
    print(operator_client.observability())
