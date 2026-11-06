import json
import unittest

from genieagent.config import ConfigError
from genieagent.http import ProviderError
from genieagent.providers.apollo import ApolloClient, _employee_bucket
from genieagent.providers.gemini import (
    GeminiClient,
    extract_text,
    normalize_qualification,
    parse_json_object,
    validate_draft,
)
from genieagent.providers.hunter import HunterClient


def transport_returning(payload, status=200, captured=None):
    def _send(method, url, headers, body):
        if captured is not None:
            captured.append({"method": method, "url": url, "headers": dict(headers), "body": body})
        return status, {}, json.dumps(payload)

    return _send


class ApolloTests(unittest.TestCase):
    def test_maps_organization_without_inventing_email(self):
        lead = ApolloClient.company_to_lead(
            None,  # type: ignore[arg-type]
            {
                "id": "org-1",
                "name": "Acme Widgets, Inc.",
                "primary_domain": "www.acme.com",
                "website_url": "https://acme.com",
                "country": "United States",
                "industry": "Retail",
                "estimated_num_employees": 120,
            },
        )
        self.assertEqual(lead["company_name"], "Acme Widgets, Inc.")
        self.assertEqual(lead["domain"], "acme.com")
        self.assertEqual(lead["email"], "")
        self.assertEqual(lead["email_status"], "unverified")
        self.assertEqual(lead["employee_range"], "51-200")
        self.assertEqual(lead["source_provider"], "apollo")
        self.assertTrue(lead["notes"].startswith("Company record from Apollo"))

    def test_search_sends_api_key_header_not_query_param(self):
        captured = []
        client = ApolloClient("secret-key", transport=transport_returning({"organizations": []}, captured=captured))
        client.search_companies(["dental clinics"], ["United States"], page=1, per_page=10)
        self.assertEqual(captured[0]["headers"]["x-api-key"], "secret-key")
        self.assertNotIn("secret-key", captured[0]["url"])
        payload = json.loads(captured[0]["body"].decode("utf-8"))
        self.assertEqual(payload["q_organization_keyword_tags"], ["dental clinics"])

    def test_requires_api_key(self):
        with self.assertRaises(ConfigError):
            ApolloClient("")

    def test_employee_bucket(self):
        self.assertEqual(_employee_bucket(5), "1-10")
        self.assertEqual(_employee_bucket(500), "201-500")
        self.assertEqual(_employee_bucket(50000), "10001+")


class HunterTests(unittest.TestCase):
    def test_choose_prefers_valid_generic_business_email(self):
        candidates = [
            {"value": "jane@acme.com", "verification": {"status": "valid", "date": "2026-01-01"}, "confidence": 90, "type": "personal"},
            {"value": "info@acme.com", "verification": {"status": "valid", "date": "2026-01-01"}, "confidence": 80, "type": "generic"},
            {"value": "acme@gmail.com", "verification": {"status": "valid"}, "confidence": 99},
            {"value": "sales@other.com", "verification": {"status": "valid"}, "confidence": 99},
        ]
        result = HunterClient.choose_business_email(None, "acme.com", candidates, verify=False)  # type: ignore[arg-type]
        self.assertEqual(result["email"], "info@acme.com")
        self.assertEqual(result["email_status"], "valid")
        self.assertTrue(result["email_verified_at"])

    def test_accept_all_is_not_marked_verified(self):
        candidates = [{"value": "info@acme.com", "verification": {"status": "accept_all"}, "confidence": 70}]
        result = HunterClient.choose_business_email(None, "acme.com", candidates, verify=False)  # type: ignore[arg-type]
        self.assertEqual(result["email_status"], "accept_all")
        self.assertEqual(result["email_verified_at"], "")

    def test_no_candidates_returns_not_found(self):
        result = HunterClient.choose_business_email(None, "acme.com", [], verify=False)  # type: ignore[arg-type]
        self.assertEqual(result["email"], "")
        self.assertEqual(result["email_status"], "not_found")

    def test_search_uses_bearer_auth(self):
        captured = []
        client = HunterClient("hunter-secret", transport=transport_returning({"data": {"emails": []}}, captured=captured))
        client.domain_search("acme.com", limit=5)
        self.assertEqual(captured[0]["headers"]["Authorization"], "Bearer hunter-secret")
        self.assertIn("domain=acme.com", captured[0]["url"])


class GeminiParsingTests(unittest.TestCase):
    def test_parses_fenced_json(self):
        self.assertEqual(parse_json_object('```json\n{"a": 1}\n```'), {"a": 1})

    def test_parses_json_with_prose(self):
        self.assertEqual(parse_json_object('Here you go:\n{"qualified": true, "score": 80}\nThanks'), {"qualified": True, "score": 80})

    def test_invalid_json_raises(self):
        with self.assertRaises(ProviderError):
            parse_json_object("not json at all")

    def test_extract_text(self):
        payload = {"candidates": [{"content": {"parts": [{"text": "hello "}, {"text": "world"}]}}]}
        self.assertEqual(extract_text(payload), "hello \nworld")

    def test_qualification_enforces_threshold(self):
        result = normalize_qualification({"qualified": True, "score": 55, "reasoning": "weak"}, min_score=70)
        self.assertFalse(result["qualified"])
        self.assertEqual(result["score"], 55)
        result = normalize_qualification({"qualified": True, "score": 91, "reasoning": "strong"}, min_score=70)
        self.assertTrue(result["qualified"])

    def test_score_is_clamped(self):
        self.assertEqual(normalize_qualification({"qualified": True, "score": 500}, min_score=70)["score"], 100)
        self.assertEqual(normalize_qualification({"qualified": True, "score": -5}, min_score=70)["score"], 0)

    def test_validate_draft_blocks_placeholders(self):
        problems = validate_draft({"subject": "Hi", "email_body": "Hello {{first_name}}, " + "x" * 100}, portfolio_url="")
        self.assertTrue(any("placeholder" in problem for problem in problems))

    def test_validate_draft_requires_portfolio(self):
        problems = validate_draft({"subject": "Hi", "email_body": "A" * 120}, portfolio_url="https://portfolio.example.com/")
        self.assertTrue(any("portfolio" in problem for problem in problems))

    def test_validate_draft_accepts_clean_message(self):
        body = "Hello,\n\nI saw your published website requirement and would like to share a short plan. " * 2
        body += "\nPortfolio: https://portfolio.example.com/\n\nKind regards,\nOwner"
        self.assertEqual(validate_draft({"subject": "Website project", "email_body": body}, "https://portfolio.example.com/"), [])


class GeminiClientTests(unittest.TestCase):
    def test_requires_api_key(self):
        with self.assertRaises(ConfigError):
            GeminiClient("")

    def test_refuses_to_qualify_without_evidence(self):
        client = GeminiClient("key", transport=transport_returning({"candidates": []}))
        lead = {"company_name": "Acme", "notes": "Company record from Apollo: company data only, no stated business requirement yet."}
        with self.assertRaises(ProviderError):
            client.qualify_lead(lead)

    def test_uses_current_model_and_structured_output(self):
        captured = []
        client = GeminiClient("key", transport=transport_returning({"candidates": [{"content": {"parts": [{"text": '{"qualified": true, "score": 88, "service_fit": "web", "reasoning": "ok"}'}]}}]}, captured=captured))
        lead = {
            "company_name": "Acme",
            "notes": "We need a new website for our retail business and have a budget of 5000 USD.",
            "source_url": "https://acme.com/project",
        }
        result = client.qualify_lead(lead, min_score=70)
        self.assertTrue(result["qualified"])
        self.assertIn("gemini-3.8-flash", captured[0]["url"])
        payload = json.loads(captured[0]["body"].decode("utf-8"))
        self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")
        self.assertIn("responseSchema", payload["generationConfig"])
        self.assertEqual(captured[0]["headers"]["x-goog-api-key"], "key")
        self.assertNotIn("key", captured[0]["url"])

    def test_retired_model_is_rejected(self):
        with self.assertRaises(ConfigError):
            GeminiClient("key", model="gemini-1.5-flash")


if __name__ == "__main__":
    unittest.main()
