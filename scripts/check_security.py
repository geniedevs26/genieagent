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
job_workflow=(ROOT/".github/workflows/remote-job-research.yml").read_text(encoding="utf-8")
research=(ROOT/"scripts/lead_research.py").read_text(encoding="utf-8")
remote_jobs=(ROOT/"scripts/remote_job_research.py").read_text(encoding="utf-8")
sync=(ROOT/"scripts/sync_candidates_supabase.py").read_text(encoding="utf-8")
outreach=(ROOT/"scripts/auto_outreach.py").read_text(encoding="utf-8")
inbox=(ROOT/"scripts/inbox_monitor.py").read_text(encoding="utf-8")
executor=(ROOT/"scripts/execute_approved_actions.py").read_text(encoding="utf-8")

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
    "id=\"researchPageRecords\"",
    "id=\"remoteJobsPanel\"",
    "async function loadRemoteJobs()",
    "data-view=\"jobs\"",
    "async function loadResearchPages()",
    "id=\"lastRunSummary\"",
    "AUTO_OUTREACH_ENABLED",
]:
    if item not in index:
        fail(f"missing expected automation status / research history UI: {item}")

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
    "cost=n('actualExpense')+n('toolCost')",
    "actual_expenses:Number(x.actualExpense)||0",
    "async function loadAudit()",
    "automationHistoryPanel",
    "financialQueuePanel",
    'id="orderStagePanel"',"async function loadStageApprovals()","data-approve-stage","data-reject-stage","clientOrderId",
]:
    if item not in index:
        fail(f"missing expected UI safety/audit gate: {item}")

for item in [
    "https://remotive.com/api/remote-jobs?limit=500",
    "https://www.arbeitnow.com/api/job-board-api",
    "https://remoteok.com/api",
    "def location_eligibility(",
    "Worldwide — India eligible",
    "Not India eligible",
    "job_opportunities?on_conflict=owner_id,source_name,source_job_id",
    "Remote job discovery:",
]:
    if item not in remote_jobs:
        fail(f"missing remote job discovery/sync requirement: {item}")
if "python scripts/remote_job_research.py" not in job_workflow:
    fail("hourly workflow must invoke remote job discovery")

if not re.search(r"(?m)^\s*max_checks_per_run\s*=\s*300\s*$", research):
    fail("research page-check limit must be an executable assignment, not part of a comment")

for item in [
    "direct_probe=DIRECT_INTENT.search(page_text)",
    "JOB_LISTING",
    "DIRECT_INTENT",
    "load_seen_urls(key,owner_id)",
    "save_seen_pages(key,seen_records)",
    "next_check_at",
    "for query in QUERIES:",
    "ThreadPoolExecutor",
    "def fetch_reddit_post(url):",
    "contact_form_verified",
    "SOCIAL_PAGE_CACHE = {}",
    "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts",
    "https://hn.algolia.com/api/v1/search_by_date",
    "potential_request=bool(intent_probe and direct_probe and not paid_probe",
    "contact_verified=bool(email or contact_form_verified or reddit_verified)",
    '"contactMethod": "Public email"',
    'site:reddit.com/r/forhire [Hiring] web developer paid project',
    '"paidSignal":"Yes" if paid_request else "Unconfirmed"',
    '"status":"Qualified lead" if paid_request else "Potential lead"',
    '"clientNeedConfirmed":"Yes"',
    '"contactVerified":"Yes"',
    "country_for(url,page_text)",
    "extract_public_phone(page_text,parser.links)",
    "\"phone\":phone,\"phone_source\":phone_source",
    "if not on_page_intent:",
]:
    if item not in research:
        fail(f"missing strict research qualification gate: {item}")

for item in [
    'item.get("status") in ("Qualified lead", "Potential lead")',
    'item.get("needStage") in ("Client need confirmed", "Buyer request found — budget unconfirmed")',
    'item.get("clientNeedConfirmed") == "Yes"',
    'item.get("contactVerified") == "Yes"',
    '"lead_status": "qualified" if item.get("paidSignal") == "Yes" else "research"',
    '"contact_form_url"',
    '"last_verified_at"',
    'research_completed',
    "known_by_url","requalified_updates","contacted_ids","existing_leads_requalified",
]:
    if item not in sync:
        fail(f"missing private sync/audit/financial gate: {item}")

for item in [
    "DAILY_LIMIT = 5",
    "FOLLOWUP_DAYS = (5, 12, 21)",
    "MAX_FOLLOWUPS = len(FOLLOWUP_DAYS)",
    "PORTFOLIO_URL = \"https://sivaprasad-portfolio.pages.dev/\"",
    "def service_profile(lead, payload):",
    "def requirement_reference(evidence):",
    "def personalised_message(lead, payload, kind, previous_bodies):",
    "Message uniqueness check failed",
    "len(prior)>=MAX_FOLLOWUPS",
    "FOLLOWUP_DAYS[len(prior)]",
    "Every prospecting message includes the portfolio",
    "imap_ready=all(",
    "reply_leads=set()",
    "bounced_leads=set()",
    'payload.get("clientNeedConfirmed")!="Yes"',
    'payload.get("contactVerified")!="Yes"',
    '"approval_status":"pending_verification"',
    '"approval_status":"failed"',
    '"automated_"+kind',
]:
    if item not in outreach:
        fail(f"missing outbound safety/logging gate: {item}")

for item in [
    "OPTOUT_RE","PROPOSAL_REQUEST_RE","ORDER_ACCEPT_RE","AGREEMENT_ACCEPT_RE","scope_intake_reply_text",
    "FINAL_ACCEPT_RE","create_or_advance_order","create_stage_request","if not order and proposal_request and not order_accept:","if not order and order_accept:",
    "financial_proposal_send","agreement_send","project_start","order_close",
    'mail.search(None,"SINCE",since,"FROM",',"search_senders=set(sent_by_recipient)|{\"mailer-daemon\",\"postmaster\"}","recent[-100:]","stable_id",
    '"client_accepted_at":None',
    'accepted_terms.get("proposed_revenue")','accepted_terms.get("payment_terms")',
    '"agreed_amount":accepted_terms.get("proposed_revenue")',
    '"action_type":"in.(email,follow_up,ai_reply,proposal,financial_proposal_send,agreement,agreement_send,milestone_delivery,final_delivery,inbound_reply)"',
    "def ai_reply_text(","def send_ai_reply(","AUTO_REPLY_BLOCK_RE","CLOUDFLARE_AI_ACCOUNT_ID","ai_reply_limit=max(0,3-ai_replies_today)",
]:
    if item not in inbox:
        fail(f"missing reply/opt-out/order transition gate: {item}")

if "mail.store(" in inbox:
    fail("inbox monitor must not change the owner's read/unread mailbox state")

for item in [
    '"status":"eq.approved"','"status":"executing"','"status":"executed"',
    "finance_ready(finance,lead)","send_stage_email","automatic retry is disabled",
    "financial_proposal_send","agreement_send","milestone_delivery","final_delivery",
]:
    if item not in executor:
        fail(f"missing explicit owner-approval execution gate: {item}")

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
    r"-----BEGIN (?:RSA |EC |OPENSSH )?" + "PRIVATE KEY-----",
    r"(?i)\b(?:service_role|secret_access_key)\s*[:=]\s*['\"]" + r"[^'\"]{12,}",
    r"\b" + "sk" + "-" + r"[A-Za-z0-9_-]{20,}\b",
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

if 'AUTO_OUTREACH_ENABLED: "true"' not in workflow:
    fail("owner-authorized automatic prospect outreach must be enabled")
if '"lead_status":"in.(qualified,research)"' not in outreach:
    fail("automatic outreach must process both paid-confirmed leads and budget-unconfirmed buyer prospects")
if "if reddit_verified and intent_probe:" not in research:
    fail("buyer-authored social requests must not be rejected by website-only direct-intent checks")
if "python scripts/execute_approved_actions.py" not in workflow:
    fail("hourly workflow must invoke the owner-approved stage executor")
if workflow.index("python scripts/inbox_monitor.py") > workflow.index("python scripts/auto_outreach.py"):
    fail("inbox replies and bounces must be processed before follow-up eligibility")
if 'HIDDEN_TAGS = {"script", "style"' not in research:
    fail("research parser must exclude script/style and other non-visible page content")
if 'PORTFOLIO_URL = "https://sivaprasad-portfolio.pages.dev/"' not in outreach:
    fail("outreach draft must include the verified portfolio URL")
if 'NON_BUYER_PUBLISHERS = {"hubspot.com"}' not in outreach:
    fail("known non-buyer publisher block missing")

print("PASS: authenticated CRM, direct-buyer research, remote job discovery, private job sync, owner-controlled outreach, and per-stage approval gates.")

# Regression policy is maintained alongside the research-first qualification workflow.
