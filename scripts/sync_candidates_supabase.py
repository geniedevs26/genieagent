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
    return host


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
        all_rows = list(csv.DictReader(source))
    # Strict gate: only explicitly confirmed requirements with a public contact
    # and a source-evidence URL may enter the CRM.
    candidates = [
        item for item in all_rows
        if item.get("status") == "Research candidate"
        
        
        and (item.get("needEvidenceUrl") or "").startswith("http")
        and (item.get("evidence") or "").strip()
    ]
    run_id = str(uuid.uuid4())
    started = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    request_json(
        f"{SUPABASE_URL}/rest/v1/agent_runs",
        key,
        method="POST",
        payload={"id": run_id, "owner_id": owner_id, "workflow_name": "daily_confirmed_lead_research",
                 "run_status": "running", "started_at": started,
                 "summary": "Daily research started; on-page requirement candidates are collected for human verification."},
        prefer="return=minimal",
    )
    request_json(
        f"{SUPABASE_URL}/rest/v1/automation_events",
        key, method="POST",
        payload={"owner_id": owner_id, "event_type": "research_started", "entity_table": "agent_runs",
                 "entity_id": run_id, "event_status": "running",
                 "summary": "Daily confirmed-lead research started",
                 "details": {"workflow": "daily_confirmed_lead_research", "source_rows": len(all_rows)}},
        prefer="return=minimal",
    )

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
            "status": "Research",
            "evidence": item.get("evidence") or "",
            "notes": "Unverified research candidate. Verify current need and contact before outreach.",
            "needStage": "Needs human verification",
            "contactVerified": "No",
            "clientNeedConfirmed": "No",
            "needEvidenceUrl": item.get("needEvidenceUrl") or item.get("source") or "",
            "financialApproved": "No",
            "scopeConfirmed": "No",
            "clientBudgetConfirmed": "No",
            "externalCostsVerified": "No",
            "paymentTerms": "",
            "costEvidenceUrl": "",
            "dealRevenue": "0",
            "toolCost": "0",
            "paymentFees": "0",
            "deliveryCost": "0",
            "contingency": "0",
            "taxReserve": "0",
            "dealCurrency": "USD",
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
            "lead_status": "new",
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
        # Create a pending financial gate for each newly confirmed lead. No quote,
        # paid tool, or client commitment is authorized by discovery alone.
        finance_rows = []
        for row in []:
            finance_rows.append({
                "owner_id": owner_id,
                "lead_id": row["id"],
                "approval_type": "quote",
                "approval_status": "pending",
                "currency": row["payload"].get("dealCurrency", "USD"),
                "proposed_revenue": 0,
                "estimated_costs": 0,
                "scope_summary": "Confirm the client's exact requested deliverable, scope, budget, payment terms and timeline before approving a quote.",
                "cost_breakdown": {"tools": 0, "fees": 0, "delivery": 0, "contingency": 0, "tax_reserve": 0},
                "evidence_url": row.get("evidence_url"),
                "payment_terms": None,
            })
        if finance_rows:
            request_json(
                f"{SUPABASE_URL}/rest/v1/financial_approvals",
                key, method="POST", payload=finance_rows, prefer="return=minimal",
            )
    finished = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    message = f"Daily run complete: {len(all_rows)} source rows reviewed; {len(candidates)} contained on-page requirement evidence; {len(rows)} new research candidates inserted; {len(candidates) - len(rows)} skipped as duplicates."
    request_json(
        f"{SUPABASE_URL}/rest/v1/agent_runs?id=eq.{run_id}",
        key, method="PATCH",
        payload={"run_status": "completed", "finished_at": finished,
                 "candidates_found": len(all_rows), "qualified_count": len(rows), "summary": message},
        prefer="return=minimal",
    )
    request_json(
        f"{SUPABASE_URL}/rest/v1/automation_events",
        key, method="POST",
        payload={"owner_id": owner_id, "event_type": "research_completed", "entity_table": "agent_runs",
                 "entity_id": run_id, "event_status": "completed", "summary": message,
                 "details": {"source_rows": len(all_rows), "passed_confirmation_gate": len(candidates),
                             "new_leads_inserted": len(rows), "duplicates_skipped": len(candidates) - len(rows)}},
        prefer="return=minimal",
    )
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
