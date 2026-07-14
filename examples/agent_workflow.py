import json
from typing import Any

from secapi_client import SecApiClient


client = SecApiClient()


def as_payload(value: Any, label: str) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    raise RuntimeError(f"{label} response was not an object")


def string_field(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return None


entity = as_payload(client.resolve_entity(ticker="AAPL"), "entity")
filing = as_payload(client.latest_filing(ticker="AAPL", form="10-K"), "latest filing")
accession_number = string_field(filing, "accessionNumber", "accession_number")
if not accession_number:
    raise RuntimeError("latest filing response did not include an accession number")
section = as_payload(client.filing_section_by_accession(
    accession_number,
    "item_1a",
    ticker="AAPL",
    mode="compact",
), "filing section")

print(json.dumps({
    "object": "secapi_sdk_agent_workflow",
    "sdk": "python",
    "workflow": {
        "ticker": "AAPL",
        "form": "10-K",
        "sectionKey": "item_1a",
        "mode": "compact",
    },
    "entity": {
        "name": string_field(entity, "name"),
        "ticker": string_field(entity, "ticker"),
        "cik": string_field(entity, "cik"),
    },
    "filing": {
        "id": string_field(filing, "id"),
        "accessionNumber": accession_number,
        "form": string_field(filing, "form"),
        "filingDate": string_field(filing, "filingDate", "filing_date"),
    },
    "section": {
        "title": string_field(section, "title"),
        "key": string_field(section, "key", "section_key"),
        "mode": "compact",
        "accessionNumber": string_field(section, "accessionNumber", "accession_number") or accession_number,
        "contentLength": len(string_field(section, "contentMd", "snippet") or ""),
    },
}, indent=2))
