import json

from secapi_client import SecApiClient


client = SecApiClient()

entity = client.resolve_entity(ticker="AAPL")
filing = client.latest_filing(ticker="AAPL", form="10-K")
accession_number = filing.get("accessionNumber") or filing.get("accession_number")
if not accession_number:
    raise RuntimeError("latest filing response did not include an accession number")
section = client.filing_section_by_accession(
    accession_number,
    "item_1a",
    ticker="AAPL",
    mode="compact",
)

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
        "name": entity.get("name"),
        "ticker": entity.get("ticker"),
        "cik": entity.get("cik"),
    },
    "filing": {
        "id": filing.get("id"),
        "accessionNumber": accession_number,
        "form": filing.get("form"),
        "filingDate": filing.get("filingDate"),
    },
    "section": {
        "title": section.get("title"),
        "key": section.get("key") or section.get("section_key"),
        "mode": "compact",
        "accessionNumber": section.get("accessionNumber") or section.get("accession_number") or accession_number,
        "contentLength": len(section.get("contentMd") or section.get("snippet") or ""),
    },
}, indent=2))
