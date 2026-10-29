#!/usr/bin/env python3
"""Sync unverified public-web research candidates to the owner's private Supabase CRM.

Required GitHub Actions secrets:
  SUPABASE_SERVICE_ROLE_KEY
  GENIE_OWNER_EMAIL

No lead details are committed to this public repository. This script only creates
new research-stage records; it never overwrites existing CRM leads or qualifies them.
"""
import csv
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

SUPABASE_URL = "https://irpqaoooosrjhviwdddo.supabase.co"
CSV_PATH = "data/research_candidates.csv"


def request_json(url, key, method="GET", payload=None, prefer=None):
    headers = {
        "apikey": key,
        "Authorization": "Bearer " + key,
        "Accept": "application/json",
    }
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if prefer:
        headers["Prefer"] = prefer
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            raw = response.read().decode("utf-8", "replace")
            return json.loads(raw) if raw.strip() else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:800]
        raise RuntimeError(f"Supabase request failed ({exc.code}): {detail}") from exc


def norm_url(value):
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    parsed = urllib.parse.urlsplit(raw if "://" in raw else "//" + raw)
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host + (parsed.path or "").rstrip("/")


def main():
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    owner_email = os.environ.get("GENIE_OWNER_EMAIL", "").strip().lower()
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not key or not owner_email:
        message = (
            "Private CRM sync skipped: add GitHub Actions secrets "
            "SUPABASE_SERVICE_ROLE_KEY and GENIE_OWNER_EMAIL to enable owner-only sync."
        )
        print(message)
        if summary_path:
            with open(summary_path, "a", encoding="utf-8") as out:
                out.write("\n## Private CRM sync\n\n" + message + "\n")
        return 0

    if not os.path.exists(CSV_PATH):
        raise RuntimeError("Research CSV was not created by the research step.")

    owner = None
    for page in range(1, 11):
        users = request_json(
            f"{SUPABASE_URL}/auth/v1/admin/users?page={page}&per_page=100",
            key,
        )
        items = users.get("users", []) if isinstance(users, dict) else []
        owner = next((u for u in items if (u.get("email") or "").lower() == owner_email), None)
        if owner or len(items) < 100:
            break
    if not owner:
        raise RuntimeError("GENIE_OWNER_EMAIL was not found in Supabase Auth users. Check the secret; no records were synced.")
    owner_id = owner["id"]

    with open(CSV_PATH, newline="", encoding="utf-8-sig") as source:
        candidates = list(csv.DictReader(source))

    query = urllib.parse.urlencode({
        "owner_id": "eq." + owner_id,
        "select": "id,website_url,payload",
        "limit": "1000",
    })
    existing = request_json(f"{SUPABASE_URL}/rest/v1/leads?{query}", key) or []
    known_urls = set()
    for row in existing:
        website = norm_url(row.get("website_url"))
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        website = website or norm_url(payload.get("website"))
        if website:
            known_urls.add(website)

    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    rows = []
    for item in candidates:
        website = norm_url(item.get("website"))
        company = (item.get("company") or "").strip()
        if not website or not company or website in known_urls:
            continue
        lead_id = str(uuid.uuid5(uuid.NAMESPACE_URL, owner_id + "|" + website))
        payload = {
            "id": lead_id,
            "company": company,
            "country": item.get("country") or "Other international",
            "contact": item.get("contact") or "",
            "email": item.get("email") or "",
            "phone": "",
            "website": item.get("website") or "",
            "source": item.get("source") or item.get("website") or "",
            "service": item.get("service") or "Other / needs confirmation",
            "status": "Researching",
            "evidence": item.get("evidence") or "Public search phrase match; verify before outreach.",
            "notes": "UNVERIFIED CANDIDATE — research phrase match only. Confirm current buyer intent and contact details before qualification.",
            "needStage": "Unverified candidate",
            "contactVerified": "No",
            "clientNeedConfirmed": "No",
            "needEvidenceUrl": "",
            "financialApproved": "No",
            "created": now[:10],
            "updated": now[:10],
            "activity": [{"date": now[:10], "text": "Added by daily public-web research. Candidate is unverified; verify before outreach."}],
        }
        rows.append({
            "id": lead_id,
            "owner_id": owner_id,
            "company_name": company,
            "website_url": item.get("website") or None,
            "contact_name": item.get("contact") or None,
            "contact_email": item.get("email") or None,
            "service_need": item.get("service") or None,
            "evidence_summary": item.get("evidence") or None,
            "evidence_url": item.get("source") or item.get("website") or None,
            "lead_status": "research",
            "payload": payload,
            "updated_at": now,
        })
        known_urls.add(website)

    if rows:
        request_json(
            f"{SUPABASE_URL}/rest/v1/leads",
            key,
            method="POST",
            payload=rows,
            prefer="return=minimal",
        )
    message = f"Private CRM sync complete: {len(rows)} new unverified candidates added; {len(candidates) - len(rows)} skipped (existing website or missing fields). No lead was qualified automatically."
    print(message)
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as out:
            out.write("\n## Private CRM sync\n\n" + message + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("Private CRM sync failed safely: " + str(exc), file=sys.stderr)
        sys.exit(1)
