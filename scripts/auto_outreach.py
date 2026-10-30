#!/usr/bin/env python3
"""Send one low-volume, relevant inquiry to each newly confirmed public requirement.

Required secrets: SUPABASE_SERVICE_ROLE_KEY, GENIE_OWNER_EMAIL, SMTP_HOST,
SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, GENIE_SENDER_EMAIL.
Set AUTO_OUTREACH_ENABLED=true only after verifying the sender and local rules.
Never sends proposals, quotes, payment requests, or follow-ups.
"""
import json, os, smtplib, sys, uuid, urllib.parse, urllib.request, urllib.error
from urllib.parse import urlparse
from datetime import datetime, timezone
from email.message import EmailMessage

SUPABASE_URL = "https://irpqaoooosrjhviwdddo.supabase.co"
DAILY_LIMIT = 5
PORTFOLIO_URL = "https://sivaprasad-portfolio.pages.dev/"
NON_BUYER_PUBLISHERS = {"hubspot.com"}

def domain_of(url):
    return (urlparse(url or "").hostname or "").lower().removeprefix("www.")


def api(path, key, method="GET", payload=None, prefer=None):
    headers={"apikey":key,"Authorization":"Bearer "+key,"Accept":"application/json"}
    data=None
    if payload is not None:
        data=json.dumps(payload).encode()
        headers["Content-Type"]="application/json"
    if prefer: headers["Prefer"]=prefer
    req=urllib.request.Request(SUPABASE_URL+path,data=data,headers=headers,method=method)
    try:
        with urllib.request.urlopen(req,timeout=25) as r:
            body=r.read().decode()
            return json.loads(body) if body.strip() else None
    except urllib.error.HTTPError as e:
        raise RuntimeError("Supabase API error "+str(e.code)+": "+e.read().decode("utf-8","replace")[:500])


def event(key, owner, event_type, status, summary, details):
    api("/rest/v1/automation_events",key,"POST",{
        "owner_id":owner,"event_type":event_type,"entity_table":"outreach_actions",
        "event_status":status,"summary":summary,"details":details
    }, "return=minimal")


def main():
    key=os.getenv("SUPABASE_SERVICE_ROLE_KEY","").strip()
    owner_email=os.getenv("GENIE_OWNER_EMAIL","").strip().lower()
    enabled=os.getenv("AUTO_OUTREACH_ENABLED","").strip().lower()=="true"
    smtp_host=os.getenv("SMTP_HOST","").strip()
    smtp_port=int(os.getenv("SMTP_PORT") or "587")
    smtp_user=os.getenv("SMTP_USERNAME","").strip()
    smtp_pass=os.getenv("SMTP_PASSWORD","").strip()
    sender=os.getenv("GENIE_SENDER_EMAIL","").strip()
    suppressed_emails={x.strip().lower() for x in os.getenv("SUPPRESSED_EMAILS","").split(",") if x.strip()}
    summary_path=os.getenv("GITHUB_STEP_SUMMARY")
    if not all([key,owner_email,enabled,smtp_host,smtp_user,smtp_pass,sender]):
        msg="Automatic outreach skipped safely. Configure owner/Supabase and SMTP secrets, then set AUTO_OUTREACH_ENABLED=true."
        print(msg)
        if summary_path:
            with open(summary_path,"a",encoding="utf-8") as f:f.write("\n## Automatic outreach\n\n"+msg+"\n")
        return 0

    users=api("/auth/v1/admin/users?page=1&per_page=100",key) or {}
    owner=next((u for u in users.get("users",[]) if (u.get("email") or "").lower()==owner_email),None)
    if not owner: raise RuntimeError("Owner email not found in Supabase Auth.")
    owner_id=owner["id"]
    # After 10 manually confirmed wins in the CRM, gently reduce outbound volume.
    won_leads=api("/rest/v1/leads?"+urllib.parse.urlencode({
        "owner_id":"eq."+owner_id,"lead_status":"eq.won","select":"id","limit":"1000"
    }),key) or []
    daily_limit=2 if len(won_leads)>=10 else DAILY_LIMIT
    if len(won_leads)>=10:
        print("10+ Won records detected: reduced daily outreach limit to 2; research cadence remains active.")
    leads=api("/rest/v1/leads?"+urllib.parse.urlencode({
        "owner_id":"eq."+owner_id,"lead_status":"eq.qualified",
        "select":"id,company_name,contact_email,website_url,evidence_summary,evidence_url,payload",
        "order":"created_at.asc","limit":"1000"
    }),key) or []
    actions=api("/rest/v1/outreach_actions?"+urllib.parse.urlencode({
        "owner_id":"eq."+owner_id,"action_type":"eq.email",
        "select":"lead_id,recipient,approval_status","limit":"5000"
    }),key) or []
    # Treat any prior attempt as already contacted; this prevents duplicate emails after a timeout or partial failure.
    already={a.get("lead_id") for a in actions if a.get("lead_id")}
    sent=0; skipped=0; failures=0
    for lead in leads:
        if sent>=daily_limit: break
        payload=lead.get("payload") if isinstance(lead.get("payload"),dict) else {}
        email=(lead.get("contact_email") or payload.get("email") or "").strip()
        website=lead.get("website_url") or payload.get("website") or ""
        evidence=(lead.get("evidence_summary") or payload.get("evidence") or "").strip()
        if email.lower() in suppressed_emails:
            skipped+=1
            print("Skipped suppressed recipient: "+email)
            continue
        evidence_url=lead.get("evidence_url") or website
        source_domain=domain_of(evidence_url)
        if (lead.get("id") in already or not email or not website or not evidence
                or source_domain == "hubspot.com" or source_domain.endswith(".hubspot.com")):
            skipped+=1
            if source_domain == "hubspot.com" or source_domain.endswith(".hubspot.com"):
                print("Skipped non-buyer educational/publisher page: "+evidence_url)
            continue
        if payload.get("clientNeedConfirmed")!="Yes" or payload.get("contactVerified")!="Yes" or not payload.get("needEvidenceUrl"):
            skipped+=1; continue
        company=lead.get("company_name") or payload.get("company") or "your team"
        service=payload.get("service") or "the stated project"
        message=EmailMessage()
        message["From"]=sender
        message["To"]=email
        message["Subject"]="Enquiry about "+service
        message["Reply-To"]=sender
        message.set_content(
            "Hello,\\n\\n"
            "My name is Siva Satya Prasad, and I represent GenieDevs. "
            "I work on practical digital solutions, including websites, web applications and automation.\\n\\n"
            "I am reaching out to ask whether your team is currently considering support for "
            +service.lower()+". If this is relevant, I would be glad to understand the scope and timeline "
            "before suggesting an approach.\\n\\n"
            "You can review my work here: "+PORTFOLIO_URL+"\\n\\n"
            "If this enquiry is not relevant, please let me know and I will not contact you again.\\n\\n"
            "Thank you for your time.\\n\\n"
            "Regards,\\nSiva Satya Prasad\\nGenieDevs"
        )
        action_id=str(uuid.uuid4())
        # Persist a pending action before sending. If logging fails, do not send.
        api("/rest/v1/outreach_actions",key,"POST",{
            "id":action_id,"owner_id":owner_id,"lead_id":lead["id"],"action_type":"email",
            "draft_subject":message["Subject"],"draft_body":message.get_content(),
            "recipient":email,"approval_status":"pending",
            "result_notes":"Queued for one-time automatic initial inquiry; strict qualification passed."
        },"return=minimal")
        try:
            with smtplib.SMTP(smtp_host,smtp_port,timeout=25) as server:
                server.starttls()
                server.login(smtp_user,smtp_pass)
                server.send_message(message)
            now=datetime.now(timezone.utc).isoformat()
            api("/rest/v1/outreach_actions?id=eq."+action_id,key,"PATCH",{
                "approval_status":"pending_verification","executed_at":now,
                "result_notes":"SMTP accepted the message for processing, but final recipient delivery is NOT verified. Excluded from contacted/email totals until a delivery-status provider confirms delivery. A later bounce remains possible."
            },"return=minimal")
            event(key,owner_id,"automated_initial_email","pending_verification",
                  "SMTP accepted message; recipient delivery is not verified",
                  {"lead_id":lead["id"],"recipient":email,"website":website,"subject":message["Subject"],"action_id":action_id})
            already.add(lead["id"]);sent+=1
        except Exception as exc:
            failures+=1
            try:
                api("/rest/v1/outreach_actions?id=eq."+action_id,key,"PATCH",{
                    "approval_status":"failed","result_notes":"SMTP send failed: "+str(exc)[:350]
                },"return=minimal")
            finally:
                event(key,owner_id,"automated_initial_email","failed",
                      "Automatic initial inquiry failed; no success claimed",
                      {"lead_id":lead["id"],"recipient":email,"error":str(exc)[:400],"action_id":action_id})

    msg=f"Automatic outreach finished: {sent} SMTP-accepted but delivery-unverified, {skipped} skipped, {failures} failed. Unverified attempts are excluded from contacted/email totals. Daily limit: {daily_limit}. Each lead receives at most one automated initial email; no follow-ups, quotes or payment requests are sent."
    print(msg)
    if summary_path:
        with open(summary_path,"a",encoding="utf-8") as f:f.write("\\n## Automatic outreach\\n\\n"+msg+"\\n")
    return 0


if __name__=="__main__":
    try: sys.exit(main())
    except Exception as exc:
        print("Automatic outreach failed safely: "+str(exc),file=sys.stderr)
        sys.exit(1)
