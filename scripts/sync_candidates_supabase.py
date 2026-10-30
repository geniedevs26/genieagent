#!/usr/bin/env python3
"""Sync automatically verified direct-business project requirements to the owner's private Supabase CRM.

Required GitHub Actions secrets:
  SUPABASE_SERVICE_ROLE_KEY
  GENIE_OWNER_EMAIL

No lead details are committed to this public repository. Only direct first-person requirements with a paid signal, same-site public email and source evidence are synced as qualified leads.
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
    # Only records that passed first-person requirement, paid-signal,
    # same-site public email and source-evidence checks enter the qualified CRM.
    candidates = [
        item for item in all_rows
        if item.get("status") == "Qualified lead"
        and item.get("needStage") == "Client need confirmed"
        and item.get("clientNeedConfirmed") == "Yes"
        and item.get("contactVerified") == "Yes"
        and (item.get("needEvidenceUrl") or "").startswith("http")
        and (item.get("evidence") or "").strip()
        and item.get("paidSignal") == "Yes"
        and bool(item.get("email"))
    ]
    run_id = str(uuid.uuid4())
    started = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    request_json(
        f"{SUPABASE_URL}/rest/v1/agent_runs",
        key,
        method="POST",
        payload={"id": run_id, "owner_id": owner_id, "workflow_name": "daily_confirmed_lead_research",
                 "run_status": "running", "started_at": started,
                 "summary": "Hourly research started; unseen pages are checked and only verified direct-business requirements are qualified."},
        prefer="return=minimal",
    )
    request_json(
        f"{SUPABASE_URL}/rest/v1/automation_events",
        key, method="POST",
        payload={"owner_id": owner_id, "event_type": "research_started", "entity_table": "agent_runs",
                 "entity_id": run_id, "event_status": "running",
                 "summary": "Hourly verified direct-business lead research started",
                 "details": {"workflow": "daily_confirmed_lead_research", "source_rows": len(all_rows)}},
        prefer="return=minimal",
    )

    query = urllib.parse.urlencode({
        "owner_id": "eq." + owner_id,
        "select": "id,website_url,payload,lead_status",
        "limit": "1000",
    })
    existing = request_json(f"{SUPABASE_URL}/rest/v1/leads?{query}", key) or []
    known_by_url = {}
    for row in existing:
        website = norm_url(row.get("website_url"))
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        website = website or norm_url(payload.get("website"))
        if website:
            known_by_url[website] = row
    action_query=urllib.parse.urlencode({"owner_id":"eq."+owner_id,"select":"lead_id,action_type","limit":"5000"})
    prior_actions=request_json(f"{SUPABASE_URL}/rest/v1/outreach_actions?{action_query}",key) or []
    contacted_ids={a.get("lead_id") for a in prior_actions if a.get("lead_id")}
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    rows = []
    requalified_updates = []
    for item in candidates:
        website = norm_url(item.get("website"))
        company = (item.get("company") or "").strip()
        if not website or not company:
            continue
        prior=known_by_url.get(website)
        if prior:
            prior_payload=prior.get("payload") if isinstance(prior.get("payload"),dict) else {}
            if (prior.get("lead_status") not in ("research","needs_review")
                    or prior.get("id") in contacted_ids
                    or prior_payload.get("doNotContact")
                    or prior_payload.get("status") in ("Opted out","Not interested")):
                continue
            lead_id=prior["id"]
            payload=dict(prior_payload)
            prior_activity=payload.get("activity") if isinstance(payload.get("activity"),list) else []
        else:
            lead_id = str(uuid.uuid5(uuid.NAMESPACE_URL, owner_id + "|" + website))
            payload = {}
            prior_activity=[]
        payload.update({
            "id": lead_id,
            "company": company,
            "country": item.get("country") or "Other international",
            "contact": item.get("contact") or "",
            "contact_url": item.get("contact_url") or "",
            "email": item.get("email") or "",
            "phone": "",
            "website": item.get("website") or "",
            "source": item.get("source") or item.get("website") or "",
            "service": item.get("service") or "Other / needs confirmation",
            "status": "Ready",
            "evidence": item.get("evidence") or "",
            "notes": "Automatically qualified from the business own public page: first-person requirement, nearby paid/contract signal and public contact email. SMTP delivery and client acceptance are still unverified.",
            "needStage": "Client need confirmed",
            "contactVerified": "Yes",
            "clientNeedConfirmed": "Yes",
            "needEvidenceUrl": item.get("needEvidenceUrl") or item.get("source") or "",
            "contactVerificationMethod": item.get("contactVerificationMethod") or "Public email listed on official business website",
            "lastVerifiedAt": now,
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
            "activity": prior_activity + [{"date": now[:10], "text": "Automatically re-verified as a direct paid business requirement with a same-site public email. SMTP delivery and client acceptance remain unverified."}],
        })
        lead_row={
            "id": lead_id,
            "owner_id": owner_id,
            "company_name": company,
            "website_url": item.get("website") or None,
            "contact_name": item.get("contact") or None,
            "contact_email": item.get("email") or None,
            "service_need": item.get("service") or None,
            "evidence_summary": item.get("evidence") or None,
            "evidence_url": item.get("needEvidenceUrl") or item.get("source") or item.get("website") or None,
            "contact_form_url": item.get("contact_url") or None,
            "last_verified_at": now,
            "source_name": item.get("discovery_method") or "public_web_search",
            "lead_status": "qualified",
            "payload": payload,
            "updated_at": now,
        }
        if prior:
            requalified_updates.append(lead_row)
        else:
            rows.append(lead_row)
            known_by_url[website] = {"id":lead_id,"lead_status":"qualified","payload":payload,"website_url":website}

    if rows:
        request_json(
            f"{SUPABASE_URL}/rest/v1/leads",
            key,
            method="POST",
            payload=rows,
            prefer="return=minimal",
        )

    for update in requalified_updates:
        request_json(f"{SUPABASE_URL}/rest/v1/leads?id=eq.{update['id']}&owner_id=eq.{owner_id}",
                     key, method="PATCH", payload=update, prefer="return=minimal")

    finished = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    message = f"Hourly run complete: {len(all_rows)} source rows reviewed; {len(candidates)} contained on-page requirement evidence; {len(rows)} new qualified leads inserted; {len(requalified_updates)} existing research records promoted after re-verification; {len(candidates) - len(rows) - len(requalified_updates)} skipped as duplicates or protected records."
    request_json(
        f"{SUPABASE_URL}/rest/v1/agent_runs?id=eq.{run_id}",
        key, method="PATCH",
        payload={"run_status": "completed", "finished_at": finished,
                 "candidates_found": len(all_rows), "qualified_count": len(rows) + len(requalified_updates), "summary": message},
        prefer="return=minimal",
    )
    request_json(
        f"{SUPABASE_URL}/rest/v1/automation_events",
        key, method="POST",
        payload={"owner_id": owner_id, "event_type": "research_completed", "entity_table": "agent_runs",
                 "entity_id": run_id, "event_status": "completed", "summary": message,
                 "details": {"source_rows": len(all_rows), "passed_confirmation_gate": len(candidates),
                             "new_leads_inserted": len(rows), "existing_leads_requalified": len(requalified_updates), "duplicates_skipped": len(candidates) - len(rows) - len(requalified_updates)}},
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
