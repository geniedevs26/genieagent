import tempfile
import unittest
from pathlib import Path

from genieagent.models import LEAD_COLUMNS
from genieagent.storage.csv_store import CsvTable, activity_table, leads_table, log_activity


class CsvTableTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="genie-csv-"))
        self.path = self.root / "leads.csv"

    def test_upsert_is_idempotent(self):
        table = leads_table(self.path)
        row = {"lead_id": "lead-1", "company_name": "Acme", "domain": "acme.com", "email_status": "unverified"}
        first = table.upsert([row])
        second = table.upsert([row])
        self.assertEqual(first["inserted"], 1)
        self.assertEqual(second["inserted"], 0)
        self.assertEqual(len(table.load()), 1)

    def test_update_and_get(self):
        table = leads_table(self.path)
        table.upsert([{"lead_id": "lead-1", "company_name": "Acme"}])
        updated = table.update("lead-1", email="info@acme.com", email_status="valid")
        self.assertEqual(updated["email"], "info@acme.com")
        self.assertEqual(table.get("lead-1")["email"], "info@acme.com")
        self.assertIsNone(table.update("missing", email="x@y.com"))

    def test_extra_columns_are_preserved(self):
        import csv as csv_module

        with open(self.path, "w", newline="", encoding="utf-8") as handle:
            writer = csv_module.DictWriter(handle, fieldnames=LEAD_COLUMNS + ["owner_note"])
            writer.writeheader()
            writer.writerow({"lead_id": "lead-1", "company_name": "Acme", "owner_note": "keep me"})
        table = leads_table(self.path)
        table.upsert([{"lead_id": "lead-1", "company_name": "Acme", "country": "USA"}])
        rows = table.load()
        self.assertEqual(rows[0]["owner_note"], "keep me")
        self.assertEqual(rows[0]["country"], "USA")

    def test_dedupe_on_upsert(self):
        table = leads_table(self.path)
        table.upsert(
            [
                {"lead_id": "a", "company_name": "Acme Inc", "domain": "acme.com", "email_status": "unverified"},
                {"lead_id": "b", "company_name": "Acme", "domain": "www.acme.com", "email": "info@acme.com", "email_status": "valid"},
            ]
        )
        rows = table.load()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["email"], "info@acme.com")

    def test_activity_log_written(self):
        log_activity(self.root / "activity.csv", "test_event", "ok", "Summary text", {"a": 1}, lead_id="lead-1")
        rows = activity_table(self.root / "activity.csv").load()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event_type"], "test_event")
        self.assertEqual(rows[0]["lead_id"], "lead-1")

    def test_empty_file_returns_no_rows(self):
        table = CsvTable(self.root / "missing.csv", ["a", "b"], "a")
        self.assertEqual(table.load(), [])


if __name__ == "__main__":
    unittest.main()
