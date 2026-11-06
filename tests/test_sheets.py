import unittest

from genieagent.models import LEAD_COLUMNS
from genieagent.storage.sheets import SheetsTable, column_letter, quote_range


class FakeSheetsAPI:
    """In-memory stand-in with the same surface used by SheetsTable."""

    def __init__(self):
        self.tabs = {}
        self.updates = 0
        self.clears = 0

    def _ensure(self, tab):
        self.tabs.setdefault(tab, [])

    def values_get(self, tab, a1="A1:ZZ20000"):
        return [list(row) for row in self.tabs.get(tab, [])]

    def values_update(self, tab, a1, values, value_input_option="RAW"):
        self._ensure(tab)
        self.updates += 1
        start = int("".join(ch for ch in a1.split(":")[0] if ch.isdigit()) or 1) - 1
        rows = self.tabs[tab]
        for offset, row in enumerate(values):
            index = start + offset
            while len(rows) <= index:
                rows.append([])
            rows[index] = ["" if cell is None else str(cell) for cell in row]
        return {}

    def values_clear(self, tab, a1):
        self.clears += 1
        start = int("".join(ch for ch in a1.split(":")[0] if ch.isdigit()) or 1) - 1
        rows = self.tabs.get(tab, [])
        del rows[start:]
        return {}

    def ensure_tab(self, tab):
        self._ensure(tab)


class SheetTableTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeSheetsAPI()
        self.table = SheetsTable(self.api, "Leads", LEAD_COLUMNS, "lead_id")

    def test_column_letter(self):
        self.assertEqual(column_letter(1), "A")
        self.assertEqual(column_letter(26), "Z")
        self.assertEqual(column_letter(27), "AA")
        self.assertEqual(column_letter(52), "AZ")

    def test_quote_range_escapes_single_quotes(self):
        self.assertEqual(quote_range("Owner's Leads", "A1"), "'Owner''s Leads'!A1")

    def test_creates_headers_then_upserts(self):
        result = self.table.upsert([{"lead_id": "l1", "company_name": "Acme", "email": "a@acme.com"}])
        self.assertEqual(result["inserted"], 1)
        headers, rows = self.table.load()
        self.assertEqual(headers[0], "lead_id")
        self.assertEqual(rows[0]["company_name"], "Acme")

    def test_second_upsert_updates_without_duplicating(self):
        self.table.upsert([{"lead_id": "l1", "company_name": "Acme"}])
        result = self.table.upsert([{"lead_id": "l1", "email_status": "valid"}])
        self.assertEqual(result["updated"], 1)
        headers, rows = self.table.load()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["email_status"], "valid")
        self.assertEqual(rows[0]["company_name"], "Acme")

    def test_owner_added_columns_survive(self):
        self.table.upsert([{"lead_id": "l1", "company_name": "Acme"}])
        headers, rows = self.table.load()
        headers.append("owner_note")
        rows[0]["owner_note"] = "hand written"
        self.table.write(headers, rows)
        self.table.upsert([{"lead_id": "l1", "country": "USA"}])
        headers, rows = self.table.load()
        self.assertIn("owner_note", headers)
        self.assertEqual(rows[0]["owner_note"], "hand written")
        self.assertEqual(rows[0]["country"], "USA")

    def test_trailing_rows_are_cleared(self):
        self.table.upsert([{"lead_id": "l1"}, {"lead_id": "l2"}, {"lead_id": "l3"}])
        self.assertEqual(len(self.table.load()[1]), 3)
        self.table.write(self.table.load()[0], self.table.load()[1][:1])
        self.assertGreater(self.api.clears, 0)
        self.assertEqual(len([row for row in self.api.tabs["Leads"][1:] if any(row)]), 1)

    def test_update_missing_returns_none(self):
        self.assertIsNone(self.table.update("nope", email="x@y.com"))


if __name__ == "__main__":
    unittest.main()
