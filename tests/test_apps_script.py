"""Offline checks for the Google Apps Script approval sidebar.

The Apps Script runtime is not available in CI, so these tests cover what can be
verified without Google: the pure decision logic (executed with Node), header
parity with the Python pipeline, the client/server wiring, the absence of any
send capability and the least-privilege manifest.
"""

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from genieagent.models import ACTIVITY_COLUMNS, LEAD_COLUMNS, OUTREACH_COLUMNS

ROOT = Path(__file__).resolve().parents[1]
APPS = ROOT / "apps_script"
LOGIC = APPS / "Logic.gs"
CODE = APPS / "Code.gs"
CLIENT = APPS / "JavaScript.html"


def js_array(source: str, name: str):
    match = re.search(r"var\s+" + re.escape(name) + r"\s*=\s*\[(.*?)\];", source, re.DOTALL)
    if not match:
        raise AssertionError(f"{name} is missing from Logic.gs")
    return re.findall(r"['\"]([^'\"]+)['\"]", match.group(1))


class HeaderParityTests(unittest.TestCase):
    def test_outreach_headers_match_pipeline(self):
        self.assertEqual(js_array(LOGIC.read_text(encoding="utf-8"), "OUTREACH_HEADERS"), OUTREACH_COLUMNS)

    def test_lead_headers_match_pipeline(self):
        self.assertEqual(js_array(LOGIC.read_text(encoding="utf-8"), "LEAD_HEADERS"), LEAD_COLUMNS)

    def test_activity_headers_match_pipeline(self):
        self.assertEqual(js_array(LOGIC.read_text(encoding="utf-8"), "ACTIVITY_HEADERS"), ACTIVITY_COLUMNS)


class LogicSuiteTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is required to execute the Apps Script logic tests")
    def test_node_logic_suite_passes(self):
        result = subprocess.run(
            ["node", str(ROOT / "tests" / "apps_script" / "logic.test.mjs")],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Apps Script logic tests passed", result.stdout)


class WiringTests(unittest.TestCase):
    def test_sidebar_calls_only_existing_public_functions(self):
        server = CODE.read_text(encoding="utf-8")
        client = CLIENT.read_text(encoding="utf-8")
        defined = set(re.findall(r"(?m)^function\s+([A-Za-z][A-Za-z0-9_]*)\s*\(", server))
        expected = {"loadApprovalState", "approveDraft", "rejectDraft", "saveOwnerEmail"}
        for name in expected:
            self.assertIn(f".{name}(", client, f"sidebar does not call {name}")
            self.assertIn(name, defined, f"{name} is not defined in Code.gs")
            self.assertFalse(name.endswith("_"), "google.script.run cannot call private helpers")
        self.assertIn("decisionBlocker(", server)
        self.assertIn("LockService.getDocumentLock()", server)

    def test_includes_resolve_to_existing_files(self):
        markup = (APPS / "Sidebar.html").read_text(encoding="utf-8")
        for name in re.findall(r"include\('([^']+)'\)", markup):
            self.assertTrue((APPS / f"{name}.html").exists(), f"missing include target {name}.html")

    def test_approval_refuses_without_owner_email(self):
        server = CODE.read_text(encoding="utf-8")
        self.assertRegex(server, r"if \(!state\.ownerEmail\)")
        self.assertIn("needsOwner: true", server)
        self.assertIn("property_(OWNER_EMAIL_PROP, '')", server)

    def test_sidebar_never_sends_and_never_fetches(self):
        forbidden = re.compile(r"\b(MailApp|GmailApp|UrlFetchApp|sendEmail|sendMail|sendMessage)\b")
        for path in list(APPS.glob("*.gs")) + list(APPS.glob("*.html")):
            source = path.read_text(encoding="utf-8")
            self.assertIsNone(forbidden.search(source), f"send capability found in {path.name}")

    def test_sidebar_writes_only_decision_columns(self):
        server = CODE.read_text(encoding="utf-8")
        writes = re.findall(r"getRange\([^)]*\)\.(?:setValue|setValues)\(", server)
        self.assertEqual(len(writes), 2, "only the decision cells and the activity header may be written")
        self.assertIn("Object.keys(built.values)", server)
        self.assertIn("activitySheet.appendRow(row)", server)


class ManifestTests(unittest.TestCase):
    def test_manifest_is_minimal_and_valid(self):
        manifest = json.loads((APPS / "appsscript.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["runtimeVersion"], "V8")
        scopes = manifest["oauthScopes"]
        self.assertIn("https://www.googleapis.com/auth/spreadsheets.currentonly", scopes)
        self.assertNotIn("https://www.googleapis.com/auth/spreadsheets", scopes)
        self.assertNotIn("https://www.googleapis.com/auth/gmail.send", scopes)


if __name__ == "__main__":
    unittest.main()
