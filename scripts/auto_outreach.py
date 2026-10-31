#!/usr/bin/env python3
"""Personalised, respectful first contact and up to three reply-aware follow-ups.

Each prospect message is composed from that lead's verified requirement and the
specific matching service. The portfolio is included in every prospecting
message. No proposal/agreement/project-stage message is sent here.
"""
import json, os, re, smtplib, sys, uuid, urllib.parse, urllib.request, urllib.error
from urllib.parse import urlparse
from datetime import datetime, timezone, timedelta
from email.message import EmailMessage

SUPABASE_URL = "https://irpqaoooosrjhviwdddo.supabase.co"
DAILY_LIMIT = 5
FOLLOWUP_DAYS = (5, 12, 21)
MAX_FOLLOWUPS = len(FOLLOWUP_DAYS)
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

def clean(value, limit=500):
    return re.sub(r"\s+"," ",str(value or "")).strip()[:limit]

def service_profile(lead, payload):
    """Return only a service actually supported by the owner's stated skills."""
    evidence=clean(" ".join([
        lead.get("service_need") or "", lead.get("evidence_summary") or "",
        payload.get("evidence") or "", payload.get("service") or "",
        payload.get("requirement") or ""
    ]),1800)
    t=(evidence+" "+clean(lead.get("service_need"),500)).lower()
    profiles=[
        (("chatbot","chat bot","conversational ai","ai assistant"),"AI chatbot / assistant",
         "I build AI-assisted chatbots and practical assistant tools, including the supporting web interface and deployment."),
        (("voice assistant","voice bot","ai calling","voice agent"),"AI voice assistant",
         "I work on AI-assisted voice and conversational tools. I would first want to understand the call flow and integrations you need."),
        (("android app","mobile app","android developer"),"Android app development",
         "I develop Android app projects with AI-assisted workflows and can discuss the screens, features and deployment requirements."),
        (("excel","spreadsheet","data cleanup","data cleaning","powerpoint","word document","data entry"),"Excel and office data work",
         "I handle Excel operations, spreadsheet cleanup, data entry and practical Word/PowerPoint work, depending on the exact scope."),
        (("telugu","translation","localization","language qa","proofreading","subtitles","transcription"),"Telugu-English language work",
         "I can help with Telugu-English translation, language QA, proofreading and transcription-related work."),
        (("logo","graphic design","thumbnail","banner","social media design","visual design"),"Graphic design and digital assets",
         "I create practical graphic assets such as logos, thumbnails, banners and social media creatives."),
        (("seo","content writer","technical writer","article writing","website content"),"Content and SEO writing",
         "I work on AI-assisted content drafting, technical writing, SEO-focused website content and editing."),
        (("automation","workflow","automate","process automation","integrations"),"Workflow automation",
         "I build practical automation workflows and AI-assisted tools to reduce repetitive business tasks."),
        (("website","web developer","web design","wordpress","shopify","landing page","web application","web app"),"Website and web application development",
         "I build responsive websites, landing pages and web applications, and can also help with deployment and basic SEO.")
    ]
    for keys,label,fit in profiles:
        if any(k in t for k in keys):
            return label,fit,evidence
    # Never invent a service match when the evidence is too vague.
    return "", "", evidence

def requirement_reference(evidence):
    """Describe the specific published need without pretending to know more than the page says."""
    e=clean(evidence,700)
    if not e: return "I came across your published project requirement"
    # Avoid pasting an entire source paragraph or making an unverified assertion.
    e=re.sub(r"^(direct requirement:\s*)","",e,flags=re.I)
    e=re.split(r"\s*\|\s*paid signal:",e,flags=re.I)[0]
    e=clean(e,220).strip(" .,:;-'\"")
    if len(e)>190: e=e[:187].rsplit(" ",1)[0]+"..."
    return "I noticed the requirement on your site: “"+e+".”"

def personalised_message(lead, payload, kind, previous_bodies):
    company=clean(lead.get("company_name"),100) or "your team"
    service,fit,evidence=service_profile(lead,payload)
    if not service:
        return None, None, "No clearly matched service in the verified requirement; do not contact."
    reference=requirement_reference(evidence)
    source=clean(lead.get("evidence_url") or lead.get("website_url"),500)
    # A stable, lead-specific opener prevents one template being reused across prospects.
    identity=clean(lead.get("id"),80)
    if kind=="email":
        subject=service+" for "+company
        opening=(
            "Hello,\n\n"
            "I’m Siva Satya Prasad. I came across your website while researching businesses "
            "with active project requirements. "+reference
        )
        body=(
            opening+"\n\n"+fit+" "
            "If this is still something you are arranging, would you be open to sharing a little "
            "about the expected scope and timing? I can then tell you honestly whether I’m a good fit.\n\n"
            "A few examples of my work are here: "+PORTFOLIO_URL+"\n\n"
            "I found the requirement here: "+source+"\n\n"
            "Thank you for your time. If the project has already been assigned, or you would prefer "
            "not to hear from me, just let me know and I will not contact you again.\n\n"
            "Kind regards,\nSiva Satya Prasad\nGenieDevs"
        )
    else:
        subject="A quick follow-up about "+service.lower()+" for "+company
        body=(
            "Hello,\n\n"
            "I wanted to follow up once on my earlier note about the requirement I saw on your site. "
            +reference+" I realise priorities can change, so I just wanted to check whether this "
            "project is still open.\n\n"+fit+" "
            "If it is active, I’d be happy to learn what you need before suggesting any approach.\n\n"
            "For convenience, my portfolio is here: "+PORTFOLIO_URL+"\n\n"
            "If you have already found someone, no problem at all. I will close the loop and will "
            "not send another follow-up.\n\n"
            "Kind regards,\nSiva Satya Prasad\nGenieDevs"
        )
    # Ensure every prospect email is unique, even where two sites publish similar wording.
    # Do not send a message if it cannot be made meaningfully distinct.
    normal=lambda x: re.sub(r"\W+"," ",(x or "").lower()).strip()
    if any(normal(body)==normal(old) for old in previous_bodies):
        body=body.replace("Thank you for your time.", "I appreciate you taking a moment to read this.")
        body=body.replace("I realise priorities can change,", "I understand your team may be busy,")
    if any(normal(body)==normal(old) for old in previous_bodies):
        body=body.replace("Kind regards,", "With thanks,")
    if any(normal(body)==normal(old) for old in previous_bodies):
        return None,None,"Message uniqueness check failed; held safely for review."
    if PORTFOLIO_URL not in body:
        return None,None,"Portfolio link missing; held safely for review."
    return subject,body,""

def send_email(key, owner_id, lead, email, sender, smtp_host, smtp_port, smtp_user, smtp_pass, kind, subject, body):
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
        "result_notes":"Standing owner authorization: individually composed, requirement-matched respectful "+("one-time follow-up" if kind=="follow_up" else "initial inquiry")+"; includes owner's portfolio."
    },"return=minimal")
    try:
        with smtplib.SMTP(smtp_host,smtp_port,timeout=25) as server:
            server.starttls()
            server.login(smtp_user,smtp_pass)
            server.send_message(msg)
        now=datetime.now(timezone.utc).isoformat()
        api("/rest/v1/outreach_actions?id=eq."+action_id,key,"PATCH",{
            "approval_status":"pending_verification","executed_at":now,
            "result_notes":"SMTP accepted the individually tailored message. Final recipient delivery is not independently verified; inbox monitoring checks replies and bounces."
        },"return=minimal")
        event(key,owner_id,"automated_"+kind,"pending_verification",
              "SMTP accepted an individually tailored "+kind+"; recipient delivery remains unverified",
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
        "select":"id,company_name,contact_email,website_url,evidence_summary,evidence_url,service_need,payload",
        "order":"created_at.asc","limit":"1000"
    }),key) or []
    actions=api("/rest/v1/outreach_actions?"+urllib.parse.urlencode({
        "owner_id":"eq."+owner_id,"action_type":"in.(email,follow_up,inbound_reply)",
        "select":"id,lead_id,recipient,approval_status,created_at,executed_at,action_type,draft_body",
        "order":"created_at.desc","limit":"5000"
    }),key) or []
    initial_by_lead={}
    followups_by_lead={}
    reply_leads=set()
    bounced_leads=set()
    previous_bodies=[]
    for a in actions:
        if a.get("draft_body"): previous_bodies.append(a["draft_body"])
        lid=a.get("lead_id")
        if not lid: continue
        kind=a.get("action_type")
        if kind=="inbound_reply": reply_leads.add(lid)
        elif kind=="email" and lid not in initial_by_lead: initial_by_lead[lid]=a
        elif kind=="follow_up": followups_by_lead.setdefault(lid,[]).append(a)
        if kind in ("email","follow_up") and a.get("approval_status")=="bounced": bounced_leads.add(lid)

    sent=skipped=failures=followups_sent=0
    held_no_match=0
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
            if not initial or len(prior)>=MAX_FOLLOWUPS or lid in reply_leads or lid in bounced_leads:
                continue
            if initial.get("approval_status")!="pending_verification":
                continue
            sent_at=parse_dt(initial.get("executed_at") or initial.get("created_at"))
            if not sent_at or now-sent_at<timedelta(days=FOLLOWUP_DAYS[len(prior)]):
                continue
            if (not email or email.lower() in suppressed or payload.get("contactVerified")!="Yes"
                    or payload.get("clientNeedConfirmed")!="Yes" or not payload.get("needEvidenceUrl")
                    or payload.get("paidSignal")!="Yes"
                    or payload.get("status") in ("Opted out","Not interested")):
                skipped+=1
                continue
            subject,body,reason=personalised_message(lead,payload,"follow_up",previous_bodies)
            if reason:
                held_no_match+=1
                continue
            if send_email(key,owner_id,lead,email,sender,smtp_host,smtp_port,smtp_user,smtp_pass,"follow_up",subject,body):
                sent+=1;followups_sent+=1;previous_bodies.append(body)
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
                or not payload.get("needEvidenceUrl") or payload.get("paidSignal")!="Yes"
                or payload.get("status") in ("Opted out","Not interested")):
            skipped+=1
            continue
        subject,body,reason=personalised_message(lead,payload,"email",previous_bodies)
        if reason:
            held_no_match+=1
            continue
        if send_email(key,owner_id,lead,email,sender,smtp_host,smtp_port,smtp_user,smtp_pass,"email",subject,body):
            sent+=1;previous_bodies.append(body)
        else: failures+=1

    msg=(f"Personalised outreach completed: {sent} SMTP-accepted messages ({followups_sent} follow-ups), "
         f"{skipped} skipped, {held_no_match} held because no clear service match/message uniqueness check failed, "
         f"{failures} failed. Every prospecting message includes the portfolio and is built from the lead's own "
         f"requirement. Up to {MAX_FOLLOWUPS} follow-ups are eligible on days {', '.join(map(str, FOLLOWUP_DAYS))} "
         "only when inbox monitoring is configured and no reply/bounce/opt-out exists. SMTP acceptance is not proof of delivery.")
    print(msg)
    if summary_path:
        with open(summary_path,"a",encoding="utf-8") as f: f.write("\n## Automatic outreach\n\n"+msg+"\n")
    return 0

if __name__=="__main__":
    try: sys.exit(main())
    except Exception as exc:
        print("Automatic outreach failed safely: "+str(exc),file=sys.stderr)
        sys.exit(1)
