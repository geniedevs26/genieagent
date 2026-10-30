#!/usr/bin/env python3
"""Static regression checks for GenieAgent automation, privacy, and financial gates."""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]

def fail(message: str) -> None:
    print(f"FAIL: {message}")
    sys.exit(1)

headers=(ROOT/"_headers").read_text(encoding="utf-8")
index=(ROOT/"index.html").read_text(encoding="utf-8")
workflow=(ROOT/".github/workflows/daily-lead-research.yml").read_text(encoding="utf-8")
research=(ROOT/"scripts/lead_research.py").read_text(encoding="utf-8")
sync=(ROOT/"scripts/sync_candidates_supabase.py").read_text(encoding="utf-8")
outreach=(ROOT/"scripts/auto_outreach.py").read_text(encoding="utf-8")

for item in [
    "X-Content-Type-Options: nosniff",
    "Referrer-Policy: strict-origin-when-cross-origin",
    "X-Frame-Options: DENY",
    "Content-Security-Policy:",
    "default-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "frame-ancestors 'none'",
]:
    if item not in headers:
        fail(f"missing security header/directive: {item}")

for item in [
    "body:not(.authenticated)>header",
    "x.needStage==='Client need confirmed'",
    "x.clientNeedConfirmed==='Yes'",
    "x.contactVerified==='Yes'",
    "x.needEvidenceUrl",
    "x.status==='Opted out'||x.status==='Not interested'",
    "x.financialApproved==='Yes'",
    "x.scopeConfirmed==='Yes'",
    "x.clientBudgetConfirmed==='Yes'",
    "x.externalCostsVerified==='Yes'",
    "x.paymentTerms",
    "x.costEvidenceUrl",
    "async function loadAudit()",
    "automationHistoryPanel",
    "financialQueuePanel",
]:
    if item not in index:
        fail(f"missing expected UI safety/audit gate: {item}")

for item in [
    'on_page_intent=bool(INTENT.search(page_text))',
    'if not on_page_intent:',
    '"status":"Research candidate"',
    '"clientNeedConfirmed":"No"',
    '"contactVerified":"No"',
]:
    if item not in research:
        fail(f"missing strict research qualification gate: {item}")

for item in [
    'item.get("status") == "Research candidate"',
    'item.get("needEvidenceUrl")',
    '"lead_status": "research"',
    'item.get("needEvidenceUrl")',
    '"lead_status": "qualified"',
    'research_completed',
    'financial_approvals',
]:
    if item not in sync:
        fail(f"missing private sync/audit/financial gate: {item}")

for item in [
    "DAILY_LIMIT = 5",
    'payload.get("clientNeedConfirmed")!="Yes"',
    'payload.get("contactVerified")!="Yes"',
    "Persist a pending action before sending",
    '"approval_status":"sent"',
    '"approval_status":"failed"',
]:
    if item not in outreach:
        fail(f"missing outbound safety/logging gate: {item}")

if "git add" in workflow or "git push" in workflow or "upload-artifact" in workflow:
    fail("daily lead workflow must not publish or upload candidate records")
if "Lead details are not committed to this public repository" not in workflow:
    fail("workflow must clearly state candidate privacy boundary")
if "python scripts/auto_outreach.py" not in workflow:
    fail("daily workflow must invoke guarded automatic outreach")
feed=ROOT/"data/qualified_leads.csv"
if feed.exists():
    import csv
    with feed.open(newline="",encoding="utf-8-sig") as handle:
        rows=list(csv.DictReader(handle))
    if rows:
        fail("public qualified lead feed must not contain any candidate or client records")

secret_patterns=[
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    r"(?i)\b(?:service_role|secret_access_key)\s*[:=]\s*['\"][^'\"]{12,}",
    r"\bsk-[A-Za-z0-9_-]{20,}\b",
]
for path in ROOT.rglob("*"):
    if not path.is_file() or ".git" in path.parts or any(part in {".github"} for part in path.parts):
        continue
    if path.suffix.lower() not in {".html",".js",".ts",".py",".json",".yml",".yaml",".toml",".md"}:
        continue
    try: content=path.read_text(encoding="utf-8")
    except (UnicodeDecodeError,OSError): continue
    for pattern in secret_patterns:
        if re.search(pattern,content):
            fail(f"possible secret material detected in {path.relative_to(ROOT)}")

print("PASS: auth gate, research-stage separation, private CRM, audit trail, financial gate, guarded outreach, and secret-pattern checks.")

# Regression policy is maintained alongside the research-first qualification workflow.
