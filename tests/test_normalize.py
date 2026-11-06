import unittest

from genieagent.normalize import (
    dedupe_key,
    dedupe_leads,
    email_matches_domain,
    is_disposable,
    is_free_mail,
    is_generic_email,
    merge_lead,
    normalize_company,
    normalize_domain,
    normalize_email,
)


class NormalizeCompanyTests(unittest.TestCase):
    def test_strips_legal_suffixes_and_punctuation(self):
        self.assertEqual(normalize_company("Acme Widgets, Inc."), "acme widgets")
        self.assertEqual(normalize_company("Bright Path Pvt. Ltd."), "bright path")
        self.assertEqual(normalize_company("The Northwind Trading Company"), "northwind trading")

    def test_keeps_meaningful_words(self):
        self.assertEqual(normalize_company("Solutions"), "solutions")
        self.assertEqual(normalize_company("Acme Solutions"), "acme")

    def test_empty_is_empty(self):
        self.assertEqual(normalize_company(""), "")
        self.assertEqual(normalize_company(None), "")


class NormalizeDomainTests(unittest.TestCase):
    def test_variants_collapse(self):
        for value in (
            "https://www.Acme.com/about?x=1",
            "http://acme.com",
            "acme.com",
            "mailto:info@acme.com",
            "https://m.acme.com/",
        ):
            self.assertEqual(normalize_domain(value), "acme.com", value)

    def test_invalid_values(self):
        self.assertEqual(normalize_domain(""), "")
        self.assertEqual(normalize_domain("not-a-domain"), "")


class NormalizeEmailTests(unittest.TestCase):
    def test_normalizes_case_and_mailto(self):
        self.assertEqual(normalize_email("MailTo:Info@Acme.COM?subject=hi"), "info@acme.com")
        self.assertEqual(normalize_email("  John.Doe@Acme.com.  "), "john.doe@acme.com")

    def test_rejects_invalid(self):
        self.assertEqual(normalize_email("nope"), "")
        self.assertEqual(normalize_email("a@b@c.com"), "")

    def test_classifiers(self):
        self.assertTrue(is_free_mail("someone@gmail.com"))
        self.assertFalse(is_free_mail("someone@acme.com"))
        self.assertTrue(is_disposable("x@mailinator.com"))
        self.assertTrue(is_generic_email("sales@acme.com"))
        self.assertTrue(is_generic_email("contactus@acme.com"))
        self.assertFalse(is_generic_email("jane@acme.com"))

    def test_domain_match(self):
        self.assertTrue(email_matches_domain("info@acme.com", "acme.com"))
        self.assertTrue(email_matches_domain("info@mail.acme.com", "acme.com"))
        self.assertFalse(email_matches_domain("info@gmail.com", "acme.com"))
        self.assertFalse(email_matches_domain("info@evilacme.com", "acme.com"))


class DedupeTests(unittest.TestCase):
    def test_dedupe_prefers_verified_email(self):
        rows = [
            {"company_name": "Acme Inc", "domain": "acme.com", "email": "", "email_status": "unverified"},
            {"company_name": "Acme", "domain": "www.acme.com", "email": "info@acme.com", "email_status": "valid"},
        ]
        unique, removed = dedupe_leads(rows)
        self.assertEqual(removed, 1)
        self.assertEqual(len(unique), 1)
        self.assertEqual(unique[0]["email"], "info@acme.com")
        self.assertEqual(unique[0]["email_status"], "valid")

    def test_separate_businesses_are_kept(self):
        rows = [
            {"company_name": "Acme", "domain": "acme.com", "country": "USA"},
            {"company_name": "Acme", "domain": "acme.co.uk", "country": "UK"},
            {"company_name": "Beta", "domain": "beta.com", "country": "USA"},
        ]
        unique, removed = dedupe_leads(rows)
        self.assertEqual(removed, 0)
        self.assertEqual(len(unique), 3)

    def test_dedupe_key_uses_company_country_fallback(self):
        key = dedupe_key({"company_name": "No Site Ltd", "country": "Canada"})
        self.assertEqual(key, "company:no site|canada")

    def test_company_match_requires_compatible_country(self):
        rows = [
            {"company_name": "Acme", "country": "USA"},
            {"company_name": "Acme", "country": "India"},
        ]
        unique, removed = dedupe_leads(rows)
        self.assertEqual(removed, 0)
        self.assertEqual(len(unique), 2)

    def test_merge_does_not_downgrade_status(self):
        base = {"company_name": "Acme", "email_status": "valid", "qualification_status": "qualified", "email_score": "90"}
        incoming = {"company_name": "Acme", "email_status": "unknown", "qualification_status": "pending", "email_score": "10"}
        merged = merge_lead(base, incoming)
        self.assertEqual(merged["email_status"], "valid")
        self.assertEqual(merged["qualification_status"], "qualified")
        self.assertEqual(merged["email_score"], "90")


if __name__ == "__main__":
    unittest.main()
