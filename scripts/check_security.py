#!/usr/bin/env python3
"""Lightweight static security regression checks for the public GenieDevs app."""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]

def fail(message: str) -> None:
    print(f"FAIL: {message}")
    sys.exit(1)

headers = (ROOT / "_headers").read_text(encoding="utf-8")
index = (ROOT / "index.html").read_text(encoding="utf-8")
workflow = (ROOT / ".github/workflows/daily-lead-research.yml").read_text(encoding="utf-8")

required_headers = [
    "X-Content-Type-Options: nosniff",
    "Referrer-Policy: strict-origin-when-cross-origin",
    "X-Frame-Options: DENY",
    "Content-Security-Policy:",
    "default-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "frame-ancestors 'none'",
]
for item in required_headers:
    if item not in headers:
        fail(f"missing security header/directive: {item}")

for item in [
    "this app is not yet login-protected",
    "Private lead feed is paused for privacy",
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
]:
    if item not in index:
        fail(f"missing expected UI safety gate: {item}")

if "git add" in workflow or "git push" in workflow or "upload-artifact" in workflow:
    fail("daily lead workflow must not publish or upload candidate records")
if "Candidate details were not committed or uploaded" not in workflow:
    fail("workflow must clearly report that candidate details are not persisted")
if (ROOT / "data/qualified_leads.csv").exists():
    fail("public qualified lead feed must not exist in repository")

# Catch common accidental private-key/token assignments without blocking public identifiers.
secret_patterns = [
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    r"(?i)\b(?:service_role|secret_access_key)\s*[:=]\s*['\"][^'\"]{12,}",
    r"\bsk-[A-Za-z0-9_-]{20,}\b",
]
for path in ROOT.rglob("*"):
    if not path.is_file() or ".git" in path.parts or any(part in {".github"} for part in path.parts):
        continue
    if path.suffix.lower() not in {".html", ".js", ".ts", ".py", ".json", ".yml", ".yaml", ".toml", ".md"}:
        continue
    try:
        content = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        continue
    for pattern in secret_patterns:
        if re.search(pattern, content):
            fail(f"possible secret material detected in {path.relative_to(ROOT)}")

print("PASS: security headers, lead privacy, qualification/financial gates, and secret-pattern checks.")
