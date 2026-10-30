#!/usr/bin/env python3
"""Automated first contact and one controlled follow-up for verified direct-business leads.

Initial email and follow-up are permitted by the owner's standing workflow instruction.
No proposal, agreement, payment request, or project-stage message is sent here; those
are handled only by the separate approval executor after an explicit owner approval.
"""
import json, os, smtplib, sys, uuid, urllib.parse, urllib.request, urllib.error
from urllib.parse import urlparse
from datetime import datetime, timezone, timedelta
from email.message import EmailMessage

SUPABASE_URL = "https://irpqaoooosrjhviwdddo.supabase.co"
DAILY_LIMIT = 5
FOLLOWUP_AFTER_DAYS = 5
MAX_FOLLOWUPS = 1
PORTFOLIO_URL = "https://sivaprasad-portfolio.pages.dev/"
NON_BUYER_PUBLISHERS = {"hubspot.com"}

def domain_of(url):
    return (urlparse(url or "").hostname or "").lower().removeprefix("www.")

def api(path, key, method="GET", payload=None, prefer=None):
    headers={"apikey":key,"Authorization":"Bearer "+key,"Accept":"application/json"}
    data=None
    if payload is not None:
        data=json.dumps(payload).encode("utf-8")
        headers["Content-Type"]="application/json"
    if prefer: headers["Prefer"]=prefer
    req=urllib.request.Request(SUPABASE_URL+path,data=data,headers=headers,method=method)
    try:
        with urllib.request.urlopen(req,timeout=25) as r:
            body=r.read().decode("utf-8","replace")
            return json.loads(body) if body.strip() else None
    except urllib.error.HTTPError as e:
        raise RuntimeError("Supabase API error "+str(e.code)+": "+e.read().decode("utf-8","replace")[:500])

def event(key, owner, event_type, status, summary, details):
    api("/rest/v1/automation_events",key,"POST",{
        "owner_id":owner,"event_type":event_type,"entity_table":"outreach_actions",
        "event_status":status,"summary":summary,"details":details
    },"return=minimal")

def parse_dt(value):
    if not value: return None
    try: return datetime.fromisoformat(value.replace("Z","+00:00")).astimezone(timezone.utc)
    except Exception: return None

def send_email(key, owner_id, lead, email, sender, smtp_host, smtp_port, smtp_user, smtp_pass, kind, body):
    service=(lead.get("payload") or {}).get("service") or "your stated project"
    company=lead.get("company_name") or "your team"
    subject=("Follow-up: " if kind=="follow_up" else "Enquiry: ")+service[:120]
    msg=EmailMessage()
    msg["From"]=sender
    msg["To"]=email
    msg["Subject"]=subject
    msg["Reply-To"]=sender
    msg.set_content(body)
    action_id=str(uuid.uuid4())
    api("/rest/v1/outreach_actions",key,"POST",{
        "id":action_id,"owner_id":owner_id,"lead_id":lead["id"],"action_type":kind,
        "draft_subject":subject,"draft_body":body,"recipient":email,"approval_status":"pending",
        "result_notes":"Standing owner authorization: automated "+("one-time follow-up" if kind=="follow_up" else "initial inquiry")+" to a verified direct-business requirement."
    },"return=minimal")
    try:
        with smtplib.SMTP(smtp_host,smtp_port,timeout=25) as server:
            server.starttls()
            server.login(smtp_user,smtp_pass)
            server.send_message(msg)
        now=datetime.now(timezone.utc).isoformat()
        api("/rest/v1/outreach_actions?id=eq."+action_id,key,"PATCH",{
            "approval_status":"pending_verification","executed_at":now,
            "result_notes":"SMTP accepted the message. Final recipient delivery is not independently verified; inbox monitoring checks replies and bounces."
        },"return=minimal")
        event(key,owner_id,"automated_"+kind,"pending_verification",
              "SMTP accepted "+kind+"; recipient delivery remains unverified",
              {"lead_id":lead["id"],"recipient":email,"website":lead.get("website_url"),"subject":subject,"action_id":action_id})
        return True
    except Exception as exc:
        api("/rest/v1/outreach_actions?id=eq."+action_id,key,"PATCH",{
            "approval_status":"failed","result_notes":"SMTP send failed: "+str(exc)[:350]
        },"return=minimal")
        event(key,owner_id,"automated_"+kind,"failed",
              "Automatic "+kind+" failed; no success claimed",
              {"lead_id":lead["id"],"recipient":email,"error":str(exc)[:400],"action_id":action_id})
        return False

def main():
    key=os.getenv("SUPABASE_SERVICE_ROLE_KEY","").strip()
    owner_email=os.getenv("GENIE_OWNER_EMAIL","").strip().lower()
    enabled=os.getenv("AUTO_OUTREACH_ENABLED","").strip().lower()=="true"
    smtp_host=os.getenv("SMTP_HOST","").strip()
    smtp_port=int(os.getenv("SMTP_PORT") or "587")
    smtp_user=os.getenv("SMTP_USERNAME","").strip()
    smtp_pass=os.getenv("SMTP_PASSWORD","").strip()
    sender=os.getenv("GENIE_SENDER_EMAIL","").strip()
    imap_ready=all(os.getenv(x,"").strip() for x in ("IMAP_HOST","IMAP_USERNAME","IMAP_PASSWORD"))
    suppressed={x.strip().lower() for x in os.getenv("SUPPRESSED_EMAILS","").split(",") if x.strip()}
    summary_path=os.getenv("GITHUB_STEP_SUMMARY")
    if not all([key,owner_email,enabled,smtp_host,smtp_user,smtp_pass,sender]):
        msg="Automatic outreach skipped safely: required owner, SMTP or enable setting is missing."
        print(msg)
        if summary_path:
            with open(summary_path,"a",encoding="utf-8") as f: f.write("\n## Automatic outreach\n\n"+msg+"\n")
        return 0

    users=api("/auth/v1/admin/users?page=1&per_page=100",key) or {}
    owner=next((u for u in users.get("users",[]) if (u.get("email") or "").lower()==owner_email),None)
    if not owner: raise RuntimeError("Owner email not found in Supabase Auth.")
    owner_id=owner["id"]
    won=api("/rest/v1/leads?"+urllib.parse.urlencode({
        "owner_id":"eq."+owner_id,"lead_status":"eq.won","select":"id","limit":"1000"
    }),key) or []
    daily_limit=2 if len(won)>=10 else DAILY_LIMIT
    leads=api("/rest/v1/leads?"+urllib.parse.urlencode({
        "owner_id":"eq."+owner_id,"lead_status":"eq.qualified",
        "select":"id,company_name,contact_email,website_url,evidence_summary,evidence_url,payload",
        "order":"created_at.asc","limit":"1000"
    }),key) or []
    actions=api("/rest/v1/outreach_actions?"+urllib.parse.urlencode({
        "owner_id":"eq."+owner_id,"action_type":"in.(email,follow_up,inbound_reply)",
        "select":"id,lead_id,recipient,approval_status,created_at,executed_at,action_type",
        "order":"created_at.desc","limit":"5000"
    }),key) or []
    initial_by_lead={}
    followups_by_lead={}
    reply_leads=set()
    bounced_leads=set()
    for a in actions:
        lid=a.get("lead_id")
        if not lid: continue
        kind=a.get("action_type")
        if kind=="inbound_reply": reply_leads.add(lid)
        elif kind=="email" and lid not in initial_by_lead: initial_by_lead[lid]=a
        elif kind=="follow_up": followups_by_lead.setdefault(lid,[]).append(a)
        if kind in ("email","follow_up") and a.get("approval_status")=="bounced": bounced_leads.add(lid)

    sent=skipped=failures=followups_sent=0
    now=datetime.now(timezone.utc)
    # Follow-ups run first, only after inbox monitoring has processed replies and bounces.
    if imap_ready:
        for lead in leads:
            if sent>=daily_limit: break
            lid=lead["id"]
            initial=initial_by_lead.get(lid)
            prior=followups_by_lead.get(lid,[])
            payload=lead.get("payload") if isinstance(lead.get("payload"),dict) else {}
            email=(lead.get("contact_email") or payload.get("email") or "").strip()
            if not initial or prior or lid in reply_leads or lid in bounced_leads:
                continue
            if initial.get("approval_status")!="pending_verification":
                continue
            sent_at=parse_dt(initial.get("executed_at") or initial.get("created_at"))
            if not sent_at or now-sent_at<timedelta(days=FOLLOWUP_AFTER_DAYS):
                continue
            if (not email or email.lower() in suppressed or payload.get("contactVerified")!="Yes"
                    or payload.get("clientNeedConfirmed")!="Yes" or not payload.get("needEvidenceUrl")
                    or payload.get("status") in ("Opted out","Not interested")):
                skipped+=1
                continue
            service=payload.get("service") or "the project"
            company=lead.get("company_name") or "your team"
            body=(
                "Hello,\n\n"
                "I am following up once on my earlier enquiry about "+service.lower()+" at "+company+". "
                "I noticed the requirement on your public page and wanted to check whether it is still active.\n\n"
                "If it is, I would be glad to understand the scope and timeline before suggesting a suitable approach. "
                "You can review my work here: "+PORTFOLIO_URL+"\n\n"
                "If the requirement has been filled or this is not relevant, no reply is needed and I will close the loop. "
                "I will not send another follow-up.\n\n"
                "Regards,\nSiva Satya Prasad\nGenieDevs"
            )
            if send_email(key,owner_id,lead,email,sender,smtp_host,smtp_port,smtp_user,smtp_pass,"follow_up",body):
                sent+=1;followups_sent+=1
            else: failures+=1

    # New initial inquiries are sent only to automatically qualified records.
    for lead in leads:
        if sent>=daily_limit: break
        lid=lead["id"]
        payload=lead.get("payload") if isinstance(lead.get("payload"),dict) else {}
        email=(lead.get("contact_email") or payload.get("email") or "").strip()
        website=lead.get("website_url") or payload.get("website") or ""
        evidence=(lead.get("evidence_summary") or payload.get("evidence") or "").strip()
        source=lead.get("evidence_url") or website
        source_domain=domain_of(source)
        if (lid in initial_by_lead or lid in followups_by_lead or not email or not website or not evidence
                or email.lower() in suppressed or source_domain=="hubspot.com" or source_domain.endswith(".hubspot.com")
                or payload.get("clientNeedConfirmed")!="Yes" or payload.get("contactVerified")!="Yes"
                or not payload.get("needEvidenceUrl") or payload.get("status") in ("Opted out","Not interested")):
            skipped+=1
            continue
        service=payload.get("service") or "the stated project"
        company=lead.get("company_name") or "your team"
        body=(
            "Hello,\n\n"
            "My name is Siva Satya Prasad, and I represent GenieDevs. "
            "I noticed your public business page mentions a requirement for "+service.lower()+". "
            "If that requirement is still active, I would be glad to understand the scope and timeline "
            "and discuss a practical approach.\n\n"
            "My work includes websites, web applications, AI-assisted tools and workflow automation. "
            "You can review my portfolio here: "+PORTFOLIO_URL+"\n\n"
            "If this requirement has already been filled or you do not want further contact, please let me know "
            "and I will close the record.\n\n"
            "Regards,\nSiva Satya Prasad\nGenieDevs"
        )
        if send_email(key,owner_id,lead,email,sender,smtp_host,smtp_port,smtp_user,smtp_pass,"email",body):
            sent+=1
        else: failures+=1

    msg=f"Automatic outreach completed: {sent} SMTP-accepted messages ({followups_sent} follow-ups), {skipped} skipped, {failures} failed. One follow-up is eligible after {FOLLOWUP_AFTER_DAYS} days only when inbox monitoring is configured and no reply/bounce/opt-out exists. Delivery is not inferred from SMTP acceptance."
    print(msg)
    if summary_path:
        with open(summary_path,"a",encoding="utf-8") as f: f.write("\n## Automatic outreach\n\n"+msg+"\n")
    return 0

if __name__=="__main__":
    try: sys.exit(main())
    except Exception as exc:
        print("Automatic outreach failed safely: "+str(exc),file=sys.stderr)
        sys.exit(1)
