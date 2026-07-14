import json
import unittest
from email.message import Message
from urllib.error import HTTPError

from secapi_client import SecApiClient, SecApiError


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status = status
        self.body = body if body is not None else {"ok": True}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.body).encode("utf-8")


def make_client():
    client = SecApiClient(api_key="test_key", base_url="https://api.secapi.test", retry=False, telemetry=False)
    seen = []

    def opener(request, timeout=None):
        seen.append({
            "url": request.full_url,
            "method": request.get_method(),
            "api_key": request.headers.get("X-api-key"),
        })
        return FakeResponse()

    client._urlopen = opener
    return client, seen


def http_error(code, headers=None, body=None, url="https://api.secapi.test/v1/fund-letters/ltr_abc/document?format=pdf"):
    message = Message()
    for name, value in (headers or {}).items():
        message[name] = value
    import io

    payload = json.dumps(body).encode("utf-8") if body is not None else b""
    return HTTPError(url, code, "error", message, io.BytesIO(payload))


class FundLetterRouteTests(unittest.TestCase):
    def test_namespace_covers_every_endpoint_on_the_frozen_surface(self):
        client, seen = make_client()

        client.fund_letters.list(ticker="AAPL")
        client.fund_letters.search(q="moat")
        client.fund_letters.semantic(q="pricing power", top_k=10)
        client.fund_letters.get("ltr_abc123")
        client.fund_letters.document("ltr_abc123")
        client.fund_letters.theses(ticker="AAPL")
        client.fund_letters.managers(q="greenhaven")
        client.fund_letters.manager_get("mgr_abc123")
        client.fund_letters.manager_overview("mgr_abc123")
        client.fund_letters.funds(manager_id="mgr_abc123")
        client.fund_letters.fund_get("fnd_abc123")
        client.fund_letters.companies(min_theses=2)
        client.fund_letters.changes(since="2026-07-01T00:00:00Z")

        paths = [entry["url"].split("https://api.secapi.test", 1)[1].split("?", 1)[0] for entry in seen]
        self.assertEqual(paths, [
            "/v1/fund-letters",
            "/v1/fund-letters/search",
            "/v1/fund-letters/semantic",
            "/v1/fund-letters/ltr_abc123",
            "/v1/fund-letters/ltr_abc123/document",
            "/v1/fund-letters/theses",
            "/v1/fund-letters/managers",
            "/v1/fund-letters/managers/mgr_abc123",
            "/v1/fund-letters/managers/mgr_abc123/overview",
            "/v1/fund-letters/funds",
            "/v1/fund-letters/funds/fnd_abc123",
            "/v1/fund-letters/companies",
            "/v1/fund-letters/changes",
        ])

    def test_list_serializes_documented_filters(self):
        client, seen = make_client()
        client.list_fund_letters(
            manager_id="mgr_1",
            fund_id="fnd_1",
            ticker="AAPL",
            cik="0000320193",
            letter_type="hedge_fund_letter",
            source="fund_website",
            distribution="fund_published",
            period="2025Q1",
            year=2025,
            quarter=1,
            published_from="2025-01-01",
            published_to="2025-06-30",
            since="2025-05-01T00:00:00Z",
            sort="published_at_desc",
            limit=25,
        )
        url = seen[0]["url"]
        self.assertIn("/v1/fund-letters?", url)
        for fragment in [
            "manager_id=mgr_1",
            "fund_id=fnd_1",
            "ticker=AAPL",
            "cik=0000320193",
            "letter_type=hedge_fund_letter",
            "source=fund_website",
            "distribution=fund_published",
            "period=2025Q1",
            "year=2025",
            "quarter=1",
            "published_from=2025-01-01",
            "published_to=2025-06-30",
            "sort=published_at_desc",
            "limit=25",
        ]:
            self.assertIn(fragment, url)

    def test_theses_joins_relationship_lists_into_a_comma_list(self):
        client, seen = make_client()
        client.list_fund_letter_theses(ticker="AAPL", relationship=["long", "added"], stance="bullish")
        self.assertIn("relationship=long%2Cadded", seen[0]["url"])
        self.assertIn("stance=bullish", seen[0]["url"])

    def test_changes_joins_type_lists_into_a_comma_list(self):
        client, seen = make_client()
        client.list_fund_letter_changes(since="2026-07-01T00:00:00Z", types=["letter.published", "thesis.extracted"])
        self.assertIn("types=letter.published%2Cthesis.extracted", seen[0]["url"])

    def test_managers_coerces_has_13f_bool_to_lowercase(self):
        client, seen = make_client()
        client.list_fund_letter_managers(has_13f=True, min_letters=4)
        self.assertIn("has_13f=true", seen[0]["url"])
        self.assertIn("min_letters=4", seen[0]["url"])

    def test_id_path_segments_are_url_encoded(self):
        client, seen = make_client()
        client.get_fund_letter("ltr_a/b c")
        self.assertIn("/v1/fund-letters/ltr_a%2Fb%20c", seen[0]["url"])


class FundLetterDocumentTests(unittest.TestCase):
    def test_markdown_document_flows_through_the_json_pipeline(self):
        client = SecApiClient(api_key="test_key", base_url="https://api.secapi.test", retry=False, telemetry=False)
        seen = []
        pages_doc = {
            "object": "fund_letter_document",
            "pages": [{"page": 1, "markdown": "Dear partners,"}],
            "sourceSha256": "ab" * 32,
            "paginationVersion": 1,
            "pageCount": 1,
        }

        def opener(request, timeout=None):
            seen.append(request.full_url)
            return FakeResponse(body=pages_doc)

        client._urlopen = opener
        result = client.get_fund_letter_document("ltr_abc123", sha="cd" * 32)
        self.assertEqual(result, pages_doc)
        self.assertIn("/v1/fund-letters/ltr_abc123/document", seen[0])
        self.assertIn("format=markdown", seen[0])
        self.assertIn(f"sha={'cd' * 32}", seen[0])

    def test_pdf_document_surfaces_the_redirect_url_without_following(self):
        client = SecApiClient(api_key="test_key", base_url="https://api.secapi.test", retry=False, telemetry=False)
        seen = []

        def no_redirect_opener(request, timeout=None):
            seen.append(request.full_url)
            raise http_error(302, headers={"Location": "https://r2.example.com/fund-letters/pdf/ab/abcd.pdf?signature=sig"})

        client._urlopen_no_redirect = no_redirect_opener
        result = client.get_fund_letter_document("ltr_abc123", format="pdf")
        self.assertEqual(result, {
            "object": "fund_letter_document_redirect",
            "letterId": "ltr_abc123",
            "format": "pdf",
            "url": "https://r2.example.com/fund-letters/pdf/ab/abcd.pdf?signature=sig",
            "status": 302,
        })
        self.assertEqual(len(seen), 1)
        self.assertIn("format=pdf", seen[0])

    def test_pdf_document_forwards_sha_for_superseded_variants(self):
        client = SecApiClient(api_key="test_key", base_url="https://api.secapi.test", retry=False, telemetry=False)
        seen = []

        def no_redirect_opener(request, timeout=None):
            seen.append(request.full_url)
            raise http_error(302, headers={"Location": "https://r2.example.com/x.pdf"})

        client._urlopen_no_redirect = no_redirect_opener
        client.get_fund_letter_document("ltr_abc123", format="pdf", sha="ef" * 32)
        self.assertIn(f"sha={'ef' * 32}", seen[0])

    def test_pdf_document_raises_document_not_distributable_for_third_party(self):
        client = SecApiClient(api_key="test_key", base_url="https://api.secapi.test", retry=False, telemetry=False)

        def no_redirect_opener(request, timeout=None):
            raise http_error(403, body={
                "object": "error",
                "code": "document_not_distributable",
                "message": "This letter's document is not distributable",
            })

        client._urlopen_no_redirect = no_redirect_opener
        with self.assertRaises(SecApiError) as context:
            client.get_fund_letter_document("ltr_abc123", format="pdf")
        self.assertEqual(context.exception.status, 403)
        self.assertEqual(context.exception.code, "document_not_distributable")

    def test_pdf_document_rejects_a_redirect_missing_location(self):
        client = SecApiClient(api_key="test_key", base_url="https://api.secapi.test", retry=False, telemetry=False)

        def no_redirect_opener(request, timeout=None):
            raise http_error(302)

        client._urlopen_no_redirect = no_redirect_opener
        with self.assertRaises(SecApiError) as context:
            client.get_fund_letter_document("ltr_abc123", format="pdf")
        self.assertEqual(context.exception.code, "client_document_redirect_missing_location")

    def test_pdf_document_tolerates_a_json_body_carrying_the_url(self):
        client = SecApiClient(api_key="test_key", base_url="https://api.secapi.test", retry=False, telemetry=False)

        def no_redirect_opener(request, timeout=None):
            return FakeResponse(body={"object": "fund_letter_document_link", "url": "https://r2.example.com/direct.pdf"})

        client._urlopen_no_redirect = no_redirect_opener
        result = client.get_fund_letter_document("ltr_abc123", format="pdf")
        self.assertEqual(result["url"], "https://r2.example.com/direct.pdf")
        self.assertEqual(result["status"], 200)

    def test_pdf_document_rejects_a_non_redirect_response_without_a_url(self):
        client = SecApiClient(api_key="test_key", base_url="https://api.secapi.test", retry=False, telemetry=False)

        def no_redirect_opener(request, timeout=None):
            return FakeResponse(body={"ok": True})

        client._urlopen_no_redirect = no_redirect_opener
        with self.assertRaises(SecApiError) as context:
            client.get_fund_letter_document("ltr_abc123", format="pdf")
        self.assertEqual(context.exception.code, "client_document_redirect_expected")


class FundLetterIteratorTests(unittest.TestCase):
    def test_iter_fund_letters_walks_cursors_and_stops_on_has_more_false(self):
        client = SecApiClient(api_key="test_key", base_url="https://api.secapi.test", retry=False, telemetry=False)
        pages = [
            {"object": "list", "data": [{"id": "ltr_1"}, {"id": "ltr_2"}], "hasMore": True, "nextCursor": "2"},
            {"object": "list", "data": [{"id": "ltr_3"}], "hasMore": False, "nextCursor": None},
        ]
        seen = []

        def opener(request, timeout=None):
            seen.append(request.full_url)
            return FakeResponse(body=pages[len(seen) - 1])

        client._urlopen = opener
        ids = [letter["id"] for letter in client.iter_fund_letters(ticker="AAPL")]
        self.assertEqual(ids, ["ltr_1", "ltr_2", "ltr_3"])
        self.assertEqual(len(seen), 2)
        self.assertIn("cursor=2", seen[1])

    def test_iter_fund_letter_theses_honors_max_items(self):
        client = SecApiClient(api_key="test_key", base_url="https://api.secapi.test", retry=False, telemetry=False)
        page = {"object": "list", "data": [{"id": "ths_1"}, {"id": "ths_2"}, {"id": "ths_3"}], "hasMore": True, "nextCursor": "3"}
        seen = []

        def opener(request, timeout=None):
            seen.append(request.full_url)
            return FakeResponse(body=page)

        client._urlopen = opener
        ids = [thesis["id"] for thesis in client.iter_fund_letter_theses(ticker="AAPL", max_items=2)]
        self.assertEqual(ids, ["ths_1", "ths_2"])
        self.assertEqual(len(seen), 1)


if __name__ == "__main__":
    unittest.main()
