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
    "def discover_social_requests():",
    "Public API discovery:",
    "numericFilters",
    "contact_form_verified",
    "SOCIAL_PAGE_CACHE = {}",
    "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts",
    "https://hn.algolia.com/api/v1/search_by_date",
    '"tags":"story"',
    "potential_request=bool(intent_probe and direct_probe and not paid_probe",
    "contact_verified=bool(email or contact_form_verified or social_verified)",
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
    "OPTOUT_RE","PROPOSAL_REQUEST_RE","ORDER_ACCEPT_RE","AGREEMENT_ACCEPT_RE","scope_intake_reply_text","if not order and not order_accept:","Automated mailbox response ignored to prevent reply loops","hourly rate|fixed price",
    "FINAL_ACCEPT_RE","create_or_advance_order","create_stage_request","if not order and not order_accept:","if not order and order_accept:",
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
    if path.suffix.lower() not in {".html",".js",".gs",".ts",".py",".json",".yml",".yaml",".toml",".md"}:
        continue
    try: content=path.read_text(encoding="utf-8")
    except (UnicodeDecodeError,OSError): continue
    for pattern in secret_patterns:
        if re.search(pattern,content):
            fail(f"possible secret material detected in {path.relative_to(ROOT)}")

if 'AUTO_OUTREACH_ENABLED: "false"' not in workflow:
    fail("outreach must remain draft-only until each message receives owner approval")
if '"lead_status":"eq.qualified"' not in outreach:
    fail("automatic outreach must process only paid-confirmed qualified leads")
if 'payload.get("paidSignal")!="Yes"' not in outreach:
    fail("initial outreach and follow-ups must require explicit paid intent")
if 'return ""' not in research or '"service":matched_service' not in research:
    fail("requests outside supported service categories must be excluded")
if "emails.update(EMAIL_RE.findall(page))" not in research:
    fail("research must extract public email addresses from page markup")
if "if social_verified and intent_probe:" not in research:
    fail("buyer-authored social requests must not be rejected by website-only direct-intent checks")
if "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts" not in research or "https://hn.algolia.com/api/v1/search_by_date" not in research:
    fail("public API discovery sources must remain enabled")
if "for query in QUERIES + COUNTRY_TARGETED_QUERIES:" in research:
    fail("unstable search-engine HTML scraping must not be part of scheduled discovery")
if "contact_verified=bool(email or contact_form_verified or social_verified)" not in research:
    fail("verified email, contact form, and active buyer reply routes must enter research CRM")
if "'ignored'" not in (ROOT/"supabase/migrations/20261031143000_allow_ignored_inbox_state.sql").read_text(encoding="utf-8"):
    fail("inbox autoresponder ignored state must be allowed by the database constraint")
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

# ---------------------------------------------------------------- new architecture
# Apollo/Hunter/Gemini/Google Sheets/Brevo/WhatsApp pipeline safety regression.
def read(relative: str) -> str:
    path = ROOT / relative
    if not path.exists():
        fail(f"missing required file: {relative}")
    return path.read_text(encoding="utf-8")

config_src = read("genieagent/config.py")
drafts_src = read("genieagent/outreach/drafts.py")
whatsapp_src = read("genieagent/outreach/whatsapp.py")
pipeline_src = read("genieagent/pipeline.py")
send_script = read("scripts/pipeline_send.py")
scheduled = read(".github/workflows/genieagent-pipeline.yml")
manual_send = read(".github/workflows/genieagent-approved-send.yml")
gitignore = read(".gitignore")
env_example = read(".env.example")

for item in [
    "outreach_send_enabled: bool = False",
    "auto_outreach_enabled: bool = False",
    "whatsapp_send_enabled: bool = False",
    'DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"',
    '"gemini-1."',
    '"automatic_outreach": False',
]:
    if item not in config_src:
        fail(f"new pipeline safety default missing from config: {item}")

for item in [
    "def approval_gate(",
    "Draft approval_status is",
    "Draft has no approver recorded",
    "Draft has no approval timestamp",
    "OUTREACH_SEND_ENABLED is false; sending is disabled",
    "Unattended sending requires AUTO_OUTREACH_ENABLED=true",
    "Email status '",
    "email_verified_at",
    "Another draft for this lead and channel was already sent",
    "WhatsApp outreach requires one",
    "Meta Cloud API requires an approved template",
    "def prepare_drafts(",
]:
    if item not in drafts_src:
        fail(f"per-message owner approval gate missing: {item}")

for item in [
    "requires an approved message template for first contact",
    "def send_template(",
    "waInstance",
    "graph.facebook.com",
    "mask_phone",
]:
    if item not in whatsapp_src:
        fail(f"WhatsApp provider safety/consent requirement missing: {item}")

for item in [
    "def stage_send(",
    "OUTREACH_SEND_ENABLED is false. Approved drafts stay queued",
    "AUTO_OUTREACH_ENABLED is false; unattended sending is disabled",
    "def redact_pii(",
    "mask_email",
]:
    if item not in pipeline_src:
        fail(f"pipeline send/privacy gate missing: {item}")

if '"--execute"' not in send_script or "not args.execute" not in send_script:
    fail("pipeline_send.py must require --execute before contacting anyone")

for item in [
    'OUTREACH_SEND_ENABLED: "false"',
    'AUTO_OUTREACH_ENABLED: "false"',
    'WHATSAPP_SEND_ENABLED: "false"',
    "python scripts/run_pipeline.py",
]:
    if item not in scheduled:
        fail(f"scheduled pipeline must never send: {item}")

if "workflow_dispatch" not in manual_send:
    fail("approved outreach workflow must be manually dispatched")
if "\n  schedule:" in manual_send:
    fail("approved outreach workflow must not have a schedule trigger")
for item in ["SEND APPROVED DRAFTS", "--execute", "pipeline_send.py"]:
    if item not in manual_send:
        fail(f"approved outreach workflow confirmation gate missing: {item}")

for item in ["data/leads.csv", "data/outreach.csv", ".env"]:
    if item not in gitignore:
        fail(f"private lead/credential file must be gitignored: {item}")

for name in ("APOLLO_API_KEY=", "HUNTER_API_KEY=", "GEMINI_API_KEY=", "BREVO_SMTP_KEY=", "GOOGLE_OAUTH_REFRESH_TOKEN="):
    match = re.search(r"(?m)^" + re.escape(name) + r"\s*$", env_example)
    if not match:
        fail(f"environment template must leave {name.rstrip('=')} empty")

n8n_dir = ROOT / "n8n"
if not n8n_dir.is_dir() or not any(n8n_dir.glob("*.workflow.json")):
    fail("importable n8n workflow definitions are required")
for path in n8n_dir.glob("*.workflow.json"):
    source = path.read_text(encoding="utf-8")
    if "approved" in path.name and "scheduleTrigger" in source:
        fail(f"manual outreach n8n workflow must not be schedulable: {path.name}")

import json as _json

dashboard_path = ROOT / "data/dashboard.json"
if not dashboard_path.exists():
    fail("data/dashboard.json must exist for the GitHub Pages dashboard")
dashboard_text = dashboard_path.read_text(encoding="utf-8")
try:
    dashboard_payload = _json.loads(dashboard_text)
except ValueError:
    fail("data/dashboard.json must be valid JSON")
for email in re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", dashboard_text):
    if "*" not in email:
        fail("published dashboard data must not contain full email addresses")
if '"phone_business"' in dashboard_text or '"phone"' in dashboard_text:
    fail("published dashboard data must not contain phone numbers")
if dashboard_payload.get("safety", {}).get("automatic_outreach") is not False:
    fail("dashboard must state that automatic outreach is disabled")

for path in [ROOT / "dashboard.html", ROOT / "assets/dashboard.js", ROOT / "assets/dashboard.css"]:
    if not path.exists():
        fail(f"GitHub Pages dashboard asset missing: {path.name}")

# ------------------------------------------------- Apps Script approval sidebar
# The sidebar may record a decision but must never be able to deliver a message.
for name in ("Code.gs", "Logic.gs", "Sidebar.html", "Stylesheet.html", "JavaScript.html", "appsscript.json"):
    if not (ROOT / "apps_script" / name).exists():
        fail(f"Apps Script approval sidebar file missing: {name}")

sidebar_sources = [read(f"apps_script/{name}") for name in ("Code.gs", "Logic.gs", "JavaScript.html")]
for source in sidebar_sources:
    if re.search(r"\b(MailApp|GmailApp|UrlFetchApp|sendEmail|sendMail)\b", source):
        fail("the approval sidebar must not contain any message-sending capability")
if "if (!state.ownerEmail)" not in sidebar_sources[0]:
    fail("the sidebar must refuse to record a decision without an owner email")
if "LockService.getDocumentLock()" not in sidebar_sources[0]:
    fail("sidebar decisions must be serialised with a document lock")
if "decisionBlocker(" not in sidebar_sources[0] or "function decisionBlocker(" not in sidebar_sources[1]:
    fail("sidebar approvals must pass the shared decision blocker")
if "approval_status: APPROVAL_APPROVED" not in sidebar_sources[1]:
    fail("sidebar must write the canonical approved status")
if "draft_approved" not in sidebar_sources[0] or "draft_rejected" not in sidebar_sources[0]:
    fail("sidebar decisions must be recorded in the activity log")
sidebar_manifest = _json.loads(read("apps_script/appsscript.json"))
if "https://www.googleapis.com/auth/spreadsheets.currentonly" not in sidebar_manifest.get("oauthScopes", []):
    fail("the sidebar manifest must request only the current spreadsheet")
if "https://www.googleapis.com/auth/spreadsheets" in sidebar_manifest.get("oauthScopes", []):
    fail("the sidebar must not request full spreadsheet access")

# ------------------------------------- strict verification (three-level gate)
verification_src = read("genieagent/verification.py")
for item in (
    "def assess_lead(",
    "def verification_gate(",
    "def apply_verification(",
    "def needs_recheck(",
    '"verified_genuine"',
    "rejected_fraud",
    "fraud_indicators",
    "verification_checked_at",
):
    if item not in verification_src:
        fail(f"strict verification requirement missing: {item}")
if re.search(r"\b(urllib\.request|requests\.|urlopen|httpx)\b", verification_src):
    fail("verification must stay offline and deterministic; no live fetching")
if "verification_gate(lead, config)" not in drafts_src:
    fail("draft preparation must pass the verification gate")
if "verification_gate(lead, config)" not in drafts_src.split("def approval_gate")[-1]:
    fail("the send approval gate must re-check strict verification")
if "verification_gate(row, config)" not in pipeline_src:
    fail("qualification must require a verified-genuine lead")
if "def stage_verify(" not in pipeline_src or "\"verify\": stage_verify" not in pipeline_src:
    fail("the pipeline must expose a verify stage")
verification_workflow = read(".github/workflows/genieagent-verification.yml")
for item in ("python scripts/pipeline_verify.py", 'OUTREACH_SEND_ENABLED: "false"', 'AUTO_OUTREACH_ENABLED: "false"'):
    if item not in verification_workflow:
        fail(f"verification workflow safety requirement missing: {item}")
for item in ('data-panel="settings"', 'data-panel="conversations"', 'data-kpi="verified_genuine"', 'id="verificationFilter"'):
    if item not in read("dashboard.html"):
        fail(f"dashboard must surface verification and the required sections: {item}")

print(
    "PASS: authenticated CRM, buyer research, Apollo/Hunter/Gemini pipeline, "
    "strict three-level lead verification with fraud screening, Google Sheets sync, "
    "owner-approved outreach (CLI and Apps Script sidebar), disabled-by-default "
    "automation, privacy-safe dashboard and static security checks."
)

# Regression policy is maintained alongside the research-first qualification workflow.
