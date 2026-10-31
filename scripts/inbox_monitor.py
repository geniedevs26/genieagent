#!/usr/bin/env python3
"""Monitor inbound replies, create owner approvals, and send narrowly scoped AI email replies.

Pricing, contractual, timing, meeting, legal, security and other commitment requests are held
for owner review. Opt-outs and bounces stop further outreach.
"""
import email
import imaplib
import smtplib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from email.header import decode_header
from email.utils import parseaddr
from email.message import EmailMessage

SUPABASE_URL = "https://irpqaoooosrjhviwdddo.supabase.co"
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
BOUNCE_RE = re.compile(r"undeliver|delivery status notification|delivery failure|returned mail|mail delivery failed|address not found|user unknown|recipient rejected|550 5\.", re.I)
OPTOUT_RE = re.compile(r"\b(?:stop emailing|stop contacting|do not contact|don't contact|remove me|unsubscribe|do not email|please stop|not interested)\b", re.I)
PROPOSAL_REQUEST_RE = re.compile(r"\b(?:please send (?:me |us )?(?:a )?(?:quote|quotation|proposal|estimate)|send (?:me |us )?(?:a )?(?:quote|quotation|proposal|estimate)|provide (?:a )?(?:quote|quotation|proposal|estimate)|share (?:a )?(?:quote|quotation|proposal|estimate)|pricing|how much (?:would|will|does) it cost|what (?:is|would be) your (?:price|fee)|interested in working with you|interested in your services|we need help with|we would like to hire you|we'd like to hire you|can you help us)\b", re.I)
ORDER_ACCEPT_RE = re.compile(r"\b(?:accept your (?:proposal|quote|quotation|offer)|approve (?:the )?(?:proposal|quote|quotation)|we(?:'d| would) like to proceed|we're ready to proceed|we are ready to proceed|please proceed with (?:the )?(?:project|work)|please proceed with (?:the )?(?:formal )?(?:project )?(?:review|estimate|quote)|go ahead with (?:the )?(?:project|work)|let's go ahead|we want to move forward|i want to move forward|i confirm i want to proceed|confirm (?:the )?order|we accept the terms|we agree to the price|we are ready to start|we're ready to start|let's move forward with (?:the )?(?:project|work))\b", re.I)
AGREEMENT_ACCEPT_RE = re.compile(r"\b(?:signed (?:the )?agreement|agreement signed|i have signed|we have signed|we agree to the agreement|we accept the agreement|we agree to the terms|terms accepted|signed copy attached)\b", re.I)
AUTO_REPLY_BLOCK_RE = re.compile(r"\b(?:price|pricing|quote|quotation|estimate|budget|cost|fee|rate|payment|invoice|contract|agreement|terms|deadline|timeline|availability|meeting|meet|call|phone|video call|interview|nda|confidential|security|legal|tax|credentials|password)\b", re.I)
FINAL_ACCEPT_RE = re.compile(r"\b(?:final delivery approved|we accept the final delivery|we approve the final delivery|final work accepted|work accepted|project completed successfully|we confirm completion|all deliverables accepted|we accept all deliverables)\b", re.I)

def api(path, key, method="GET", payload=None, prefer=None):
    headers={"apikey":key,"Authorization":"Bearer "+key,"Accept":"application/json"}
    data=None
    if payload is not None:
        data=json.dumps(payload).encode("utf-8")
        headers["Content-Type"]="application/json"
    if prefer: headers["Prefer"]=prefer
    req=urllib.request.Request(SUPABASE_URL+path,data=data,headers=headers,method=method)
    try:
        with urllib.request.urlopen(req,timeout=25) as response:
            body=response.read().decode("utf-8","replace")
            return json.loads(body) if body.strip() else None
    except urllib.error.HTTPError as exc:
        raise RuntimeError("Supabase API error "+str(exc.code)+": "+exc.read().decode("utf-8","replace")[:500])

def event(key, owner_id, event_type, status, summary, details):
    api("/rest/v1/automation_events",key,"POST",{
        "owner_id":owner_id,"event_type":event_type,"entity_table":"client_orders",
        "event_status":status,"summary":summary,"details":details
    },"return=minimal")

def decoded(value):
    parts=decode_header(value or "")
    return " ".join((p.decode(enc or "utf-8","replace") if isinstance(p,bytes) else p) for p,enc in parts)

def body_text(msg):
    chunks=[]
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.get_content_maintype()=="multipart" or part.get_content_type() not in ("text/plain","text/html"): continue
        try:
            raw=part.get_payload(decode=True) or b""
            chunks.append(raw.decode(part.get_content_charset() or "utf-8","replace"))
        except Exception: continue
    return re.sub(r"<[^>]+>"," "," ".join(chunks))

def create_stage_request(key, owner_id, order, stage, title, subject, body):
    q=urllib.parse.urlencode({
        "owner_id":"eq."+owner_id,"order_id":"eq."+order["id"],
        "stage":"eq."+stage,"status":"eq.pending","select":"id","limit":"1"
    })
    existing=api("/rest/v1/approval_requests?"+q,key) or []
    if existing: return existing[0]["id"]
    rows=api("/rest/v1/approval_requests",key,"POST",[{
        "owner_id":owner_id,"order_id":order["id"],"lead_id":order["lead_id"],
        "stage":stage,"title":title,"document_subject":subject,"document_body":body,"status":"pending"
    }],"return=representation") or []
    return rows[0]["id"] if rows else None

def create_or_advance_order(key, owner_id, lead, sender, subject, reply_body, now):
    combined=subject+"\n"+reply_body
    if OPTOUT_RE.search(combined):
        payload=lead.get("payload") if isinstance(lead.get("payload"),dict) else {}
        payload["status"]="Opted out"
        payload["contactVerified"]="No"
        payload["doNotContact"]=True
        payload["activity"]=(payload.get("activity") if isinstance(payload.get("activity"),list) else [])+[{
            "date":now[:10],"text":"Client requested no further contact. Outreach suppression applied."
        }]
        api("/rest/v1/leads?id=eq."+lead["id"],key,"PATCH",{
            "payload":payload,"lead_status":"do_not_contact","updated_at":now
        },"return=minimal")
        event(key,owner_id,"client_opt_out","blocked","Client opt-out recorded; all future outreach suppressed.",{"lead_id":lead["id"],"sender":sender})
        return "opt_out"

    q=urllib.parse.urlencode({"owner_id":"eq."+owner_id,"lead_id":"eq."+lead["id"],"select":"*","limit":"1"})
    found=api("/rest/v1/client_orders?"+q,key) or []
    order=found[0] if found else None
    proposal_request=bool(PROPOSAL_REQUEST_RE.search(combined))
    order_accept=bool(ORDER_ACCEPT_RE.search(combined))
    agreement_accept=bool(AGREEMENT_ACCEPT_RE.search(combined))
    final_accept=bool(FINAL_ACCEPT_RE.search(combined))
    payload=lead.get("payload") if isinstance(lead.get("payload"),dict) else {}
    company=lead.get("company_name") or payload.get("company") or "Client"
    service=lead.get("service_need") or payload.get("service") or "the requested project"
    evidence=lead.get("evidence_summary") or payload.get("evidence") or "Client's stated requirement"
    safe_evidence="Client reply from "+sender+"; subject: "+subject[:160]+"; response excerpt: "+re.sub(r"\s+"," ",reply_body)[:350]
    if not order and not order_accept:
        # Keep the owner out of routine pre-sales discovery. Gather scope and buyer budget
        # first; no price, delivery date, agreement or commitment is offered here.
        payload["buyerScopeRequests"]=(payload.get("buyerScopeRequests") if isinstance(payload.get("buyerScopeRequests"),list) else [])+[{
            "received_at":now,"sender":sender,"subject":subject[:180],
            "message_excerpt":re.sub(r"\s+"," ",reply_body)[:700]
        }]
        payload["status"]="Pre-sales discovery"
        payload["lastClientReplyAt"]=now
        payload["activity"]=(payload.get("activity") if isinstance(payload.get("activity"),list) else [])+[{
            "date":now[:10],"text":"Buyer requested pricing or more information. GenieAgent automatically requested exact scope, deliverables and budget; no owner approval or financial commitment was created."
        }]
        api("/rest/v1/leads?id=eq."+lead["id"],key,"PATCH",{"payload":payload,"updated_at":now},"return=minimal")
        event(key,owner_id,"buyer_scope_intake","automated",
            "Buyer requested pricing; automated scope and budget clarification sent before owner involvement.",
            {"lead_id":lead["id"],"sender":sender,"subject":subject[:160]})
        return "scope_intake_reply"

    if not order and order_accept:
        prior_buyer_details=payload.get("buyerScopeRequests") if isinstance(payload.get("buyerScopeRequests"),list) else []
        prior_text=" ".join(
            item.get("message_excerpt","") for item in prior_buyer_details if isinstance(item,dict)
        )
        all_buyer_details=prior_text+" "+reply_body
        has_scope=bool(re.search(r"\\b(?:website|web app|mobile app|android app|chatbot|dashboard|spreadsheet|Excel|WordPress|Shopify|deliverables?|features?|pages?|screens?|automation|workflow|design|develop|build|redesign|integrate|translate|clean)\\b",all_buyer_details,re.I))
        has_budget=bool(re.search(r"(?:[$€£₹]\\s?\\d|\\b(?:USD|EUR|GBP|INR|AUD|CAD)\\s?\\d|\\d[\\d,.]*\\s?(?:USD|EUR|GBP|INR|AUD|CAD)\\b|\\b(?:budget|budgeted|hourly rate|fixed price|per hour)\\b)",all_buyer_details,re.I))
        has_timing=bool(re.search(r"\\b(?:by|before|within|deadline|timeline|weeks?|months?|days?|urgent|asap|flexible)\\b",all_buyer_details,re.I))
        if not (has_scope and has_budget and has_timing):
            prior_buyer_details.append({
                "received_at":now,"sender":sender,"subject":subject[:180],
                "message_excerpt":re.sub(r"\\s+"," ",reply_body)[:700]
            })
            payload["buyerScopeRequests"]=prior_buyer_details[-8:]
            payload["status"]="Pre-sales discovery"
            api("/rest/v1/leads?id=eq."+lead["id"],key,"PATCH",{"payload":payload,"updated_at":now},"return=minimal")
            event(key,owner_id,"buyer_scope_intake","automated",
                "Buyer expressed proceed intent, but required scope, budget or timing details are incomplete. Automatic clarification requested before order confirmation.",
                {"lead_id":lead["id"],"sender":sender,"subject":subject[:160]})
            return "scope_intake_reply"
        buyer_details=" | ".join(clean.get("message_excerpt","") if isinstance(clean,dict) else "" for clean in prior_buyer_details)
        buyer_details=re.sub(r"\s+"," ",buyer_details)[:1800]
        current_details=re.sub(r"\s+"," ",reply_body)[:700]
        scope=service+" — "+evidence+" — Buyer-provided details: "+(buyer_details+" | "+current_details).strip(" |")
        currency=payload.get("dealCurrency") or "USD"
        created=api("/rest/v1/client_orders",key,"POST",[{
            "owner_id":owner_id,"lead_id":lead["id"],"client_name":company,
            "scope_summary":scope,"agreed_currency":currency,
            "order_status":"awaiting_financial_approval","client_response_at":now,
            "proposal_requested_at":now,
            "client_accepted_at":None,
            "client_acceptance_evidence":None
        }],"return=representation") or []
        if not created: raise RuntimeError("Client order opportunity could not be recorded.")
        order=created[0]
        existing_finance=api("/rest/v1/financial_approvals?"+urllib.parse.urlencode({
            "owner_id":"eq."+owner_id,"lead_id":"eq."+lead["id"],"select":"id","limit":"1"
        }),key) or []
        if not existing_finance:
            api("/rest/v1/financial_approvals",key,"POST",[{
                "owner_id":owner_id,"lead_id":lead["id"],"approval_type":"quote",
                "approval_status":"pending","currency":currency,"proposed_revenue":0,
                "estimated_costs":0,"scope_summary":scope,
                "cost_breakdown":{"tools":0,"fees":0,"delivery":0,"contingency":0,"tax_reserve":0},
                "evidence_url":lead.get("evidence_url") or payload.get("needEvidenceUrl"),
                "payment_terms":None,"decision_notes":"Awaiting owner pricing, cost and payment-term review."
            }],"return=minimal")
        proposal_body=(
            "FINANCIAL PROPOSAL — DRAFT FOR OWNER REVIEW\n\n"
            "Client: "+company+"\n"
            "Requested service: "+service+"\n"
            "Scope from the public requirement: "+evidence+"\n\n"
            "Deliverables: Confirm exact deliverables and exclusions before sending.\n"
            "Price and currency: Enter the owner-approved amount in the financial review.\n"
            "Payment terms: Enter verified terms before sending.\n"
            "Timeline: Confirm after scope and availability review.\n\n"
            "This draft must be completed and approved by the owner before it is sent."
        )
        create_stage_request(key,owner_id,order,"financial_proposal_send",
            "Review financial proposal for "+company,"Financial proposal — "+company,proposal_body)
        payload["status"]="Replied"
        payload["emailDeliveryStatus"]="reply_received"
        payload["lastClientReplyAt"]=now
        payload["clientOrderId"]=order["id"]
        payload["clientProposalRequestedAt"]=now
        payload["clientNeedConfirmed"]="Yes"
        payload["contactVerified"]="Yes"
        payload["needStage"]="Client need confirmed"
        payload["activity"]=(payload.get("activity") if isinstance(payload.get("activity"),list) else [])+[{
            "date":now[:10],"text":"Inbound client reply received from "+sender+"."
        },{
            "date":now[:10],"text":"Client requested pricing/proposal or expressed clear hiring intent. Financial proposal approval created; nothing sent."
        }]
        api("/rest/v1/leads?id=eq."+lead["id"],key,"PATCH",{"payload":payload,"updated_at":now},"return=minimal")
        event(key,owner_id,"client_requested_proposal","approval_pending",
            "Client expressed buying intent; financial proposal is waiting for owner approval.",
            {"lead_id":lead["id"],"order_id":order["id"],"sender":sender})
        return "proposal_approval_created"

    if not order: return "reply_recorded"
    status=order.get("order_status")
    if status in ("financial_proposal_sent","financial_proposal_approved") and order_accept:
        finance_rows=api("/rest/v1/financial_approvals?"+urllib.parse.urlencode({
            "owner_id":"eq."+owner_id,"lead_id":"eq."+lead["id"],
            "select":"proposed_revenue,currency,payment_terms,scope_summary","limit":"1"
        }),key) or []
        accepted_terms=finance_rows[0] if finance_rows else {}
        accepted_patch={
            "client_accepted_at":now,"client_acceptance_evidence":safe_evidence,
            "order_status":"awaiting_agreement_approval"
        }
        if accepted_terms:
            accepted_patch.update({
                "agreed_amount":accepted_terms.get("proposed_revenue"),
                "agreed_currency":accepted_terms.get("currency") or order.get("agreed_currency") or "USD",
                "payment_terms":accepted_terms.get("payment_terms"),
                "scope_summary":accepted_terms.get("scope_summary") or order.get("scope_summary")
            })
        api("/rest/v1/client_orders?id=eq."+order["id"],key,"PATCH",accepted_patch,"return=minimal")
        agreement_body=(
            "PROJECT AGREEMENT — DRAFT FOR OWNER REVIEW\n\n"
            "Client: "+company+"\nProject scope: "+order.get("scope_summary","")+"\n"
            "Agreed price: Confirm against the approved financial proposal.\n"
            "Payment terms: Confirm the approved deposit and milestone schedule.\n"
            "Timeline: Confirm milestones and delivery dates.\n"
            "Change requests: Out-of-scope changes require a separate written estimate.\n"
            "Acceptance: Work begins only after the agreement is accepted and the owner approves project start.\n\n"
            "This draft requires owner review and approval before it is sent."
        )
        create_stage_request(key,owner_id,order,"agreement_send",
            "Review project agreement for "+company,"Project agreement — "+company,agreement_body)
        event(key,owner_id,"client_accepted_proposal","approval_pending",
            "Client accepted the financial proposal; agreement is waiting for owner approval.",
            {"lead_id":lead["id"],"order_id":order["id"],"sender":sender})
        return "agreement_approval_created"

    if status=="agreement_sent" and agreement_accept:
        api("/rest/v1/client_orders?id=eq."+order["id"],key,"PATCH",{
            "order_status":"awaiting_project_start_approval"
        },"return=minimal")
        create_stage_request(key,owner_id,order,"project_start",
            "Approve project start for "+company,"Project start approval — "+company,
            "The client has confirmed acceptance of the agreement. Review the agreed scope, payment status, timeline and readiness, then approve or reject project start.")
        event(key,owner_id,"client_accepted_agreement","approval_pending",
            "Client accepted the agreement; project start is waiting for owner approval.",
            {"lead_id":lead["id"],"order_id":order["id"],"sender":sender})
        return "project_start_approval_created"

    if status=="final_delivery_sent" and final_accept:
        api("/rest/v1/client_orders?id=eq."+order["id"],key,"PATCH",{
            "order_status":"awaiting_order_close_approval"
        },"return=minimal")
        create_stage_request(key,owner_id,order,"order_close",
            "Approve completion and close order for "+company,"Order closure approval — "+company,
            "The client has accepted the final delivery. Verify all deliverables, payments, access handover and outstanding obligations, then approve order closure.")
        event(key,owner_id,"client_accepted_final_delivery","approval_pending",
            "Client accepted final delivery; order closure is waiting for owner approval.",
            {"lead_id":lead["id"],"order_id":order["id"],"sender":sender})
        return "order_close_approval_created"
    return "reply_recorded"

def scope_intake_reply_text(lead, subject, body):
    """Automated pre-sales qualification. Never quotes or creates a binding promise."""
    service=(lead.get("service_need") or "your project").strip()
    text_value=re.sub(r"\s+"," ",(subject or "")+" "+(body or "")).strip()
    asks=[]
    has_scope=bool(re.search(r"\b(?:build|develop|design|redesign|create|fix|integrate|automate|translate|clean|deliver|features?|pages?|screens?|dashboard|chatbot|website|app|spreadsheet|workflow)\b",text_value,re.I))
    has_budget=bool(re.search(r"(?:[$€£₹]\s?\d|\b(?:USD|EUR|GBP|INR|AUD|CAD)\s?\d|\d[\d,.]*\s?(?:USD|EUR|GBP|INR|AUD|CAD)\b|\b(?:budget|budgeted|hourly rate|fixed price|per hour)\b)",text_value,re.I))
    has_timing=bool(re.search(r"\b(?:by|before|within|deadline|timeline|weeks?|months?|days?|urgent|asap|flexible)\b",text_value,re.I))
    if not has_scope: asks.append("the exact deliverables and features you need")
    if not has_budget: asks.append("your expected budget range and currency")
    if not has_timing: asks.append("your preferred timeframe or deadline")
    if asks:
        next_step="Could you share "+", ".join(asks)+"? Please do not send passwords, private credentials or confidential data."
    else:
        next_step="Thank you — I have the initial scope, budget and timing details. If you want me to move to the formal project review, please reply clearly: “I confirm I want to proceed.”"
    return (
        "Hello,\n\nThank you for getting back to me about "+service+". "
        +next_step+"\n\n"
        "I will review the information and confirm whether the work fits my services. "
        "No price, delivery date, payment term, agreement or project commitment is made by this email.\n\n"
    )


def ai_reply_text(account_id, token, subject, body, lead):
    if not account_id or not token or AUTO_REPLY_BLOCK_RE.search(subject+"\n"+body):
        return ""
    prompt={"messages":[
      {"role":"system","content":"Return only a JSON object with one string field named reply. Do not add markdown or explanation. Write a brief email for Siva Satya Prasad. Facts: services include responsive websites/web apps, landing pages, AI chatbots, Android apps, workflow automation, Excel/Word/PowerPoint/data work, Telugu-English translation/QA, content/SEO/technical writing and graphics. Portfolio https://sivaprasad-portfolio.pages.dev/. Coordinate by email. Never invent client history, credentials, years, availability, prices, timelines, guarantees or compliance. Never accept work, negotiate, quote, promise or agree to terms. If asked about price, budget, payment, contract, deadline, availability, calls/meetings, legal/security/confidential matters, return empty reply. For simple capability questions, answer using only facts and ask for non-confidential scope details by email. Under 100 words."},
      {"role":"user","content":"Service: "+str(lead.get("service_need") or "")+"\nRequirement: "+str(lead.get("evidence_summary") or "")+"\nSubject: "+subject[:200]+"\nMessage: "+body[:2500]}
    ],"max_tokens":220,"temperature":0.1}
    url="https://api.cloudflare.com/client/v4/accounts/"+account_id+"/ai/run/@cf/meta/llama-3.1-8b-instruct-fp8"
    req=urllib.request.Request(url,data=json.dumps(prompt).encode(),headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=30) as response:
            data=json.loads(response.read().decode("utf-8","replace"))
        raw=(data.get("result") or {}).get("response") or ""
        match=re.search(r"\{.*\}",raw,re.S)
        if not match: return ""
        answer=str(json.loads(match.group(0)).get("reply") or "").strip()
        if not answer or len(answer)>900 or AUTO_REPLY_BLOCK_RE.search(answer): return ""
        if re.search(r"\b(?:guarantee|promise|certified|available immediately|will finish by|my clients include)\b",answer,re.I): return ""
        return re.sub(r"\s+"," ",answer)
    except Exception as exc:
        print("AI reply held safely: "+str(exc)[:180])
        return ""

def send_ai_reply(key, owner_id, lead, recipient, subject, answer, message_id, host, port, username, password, sender):
    import uuid
    action_id=str(uuid.uuid4())
    msg=EmailMessage()
    msg["From"]=sender
    msg["To"]=recipient
    msg["Subject"]=subject if subject.lower().startswith("re:") else "Re: "+subject
    msg["Reply-To"]=sender
    if message_id:
        msg["In-Reply-To"]=message_id
        msg["References"]=message_id
    msg.set_content(answer+"\n\nKind regards,\nSiva Satya Prasad\nGenieDevs")
    api("/rest/v1/outreach_actions",key,"POST",[{"id":action_id,"owner_id":owner_id,"lead_id":lead["id"],"action_type":"ai_reply","draft_subject":msg["Subject"],"draft_body":answer,"recipient":recipient,"approval_status":"pending","result_notes":"Automated buyer reply; deterministic scope intake or bounded factual response. No quote or binding commitment."}],"return=minimal")
    try:
        with smtplib.SMTP(host,port,timeout=25) as server:
            server.starttls()
            server.login(username,password)
            server.send_message(msg)
        now=datetime.now(timezone.utc).isoformat()
        api("/rest/v1/outreach_actions?id=eq."+action_id,key,"PATCH",{"approval_status":"pending_verification","executed_at":now,"result_notes":"SMTP accepted AI reply; delivery not independently verified."},"return=minimal")
        event(key,owner_id,"automated_client_reply","pending_verification","Automated client email reply sent; scope intake contains no quote or binding commitment.",{"lead_id":lead["id"],"recipient":recipient,"action_id":action_id})
        return True
    except Exception as exc:
        api("/rest/v1/outreach_actions?id=eq."+action_id,key,"PATCH",{"approval_status":"failed","result_notes":"AI reply SMTP failed: "+str(exc)[:250]},"return=minimal")
        return False

def main():
    key=os.getenv("SUPABASE_SERVICE_ROLE_KEY","").strip()
    owner_email=os.getenv("GENIE_OWNER_EMAIL","").strip().lower()
    host=os.getenv("IMAP_HOST","").strip()
    username=os.getenv("IMAP_USERNAME","").strip()
    password=os.getenv("IMAP_PASSWORD","").strip()
    port=int(os.getenv("IMAP_PORT") or "993")
    folder=os.getenv("IMAP_FOLDER") or "INBOX"
    summary_path=os.getenv("GITHUB_STEP_SUMMARY")
    if not all([key,owner_email,host,username,password]):
        msg="Inbox monitor skipped safely: configure IMAP_HOST, IMAP_USERNAME, IMAP_PASSWORD, SUPABASE_SERVICE_ROLE_KEY and GENIE_OWNER_EMAIL."
        print(msg)
        if summary_path:
            with open(summary_path,"a",encoding="utf-8") as f: f.write("\n## Inbox monitoring\n\n"+msg+"\n")
        return 0

    users=api("/auth/v1/admin/users?page=1&per_page=100",key) or {}
    owner=next((u for u in users.get("users",[]) if (u.get("email") or "").lower()==owner_email),None)
    if not owner: raise RuntimeError("Owner email not found in Supabase Auth.")
    owner_id=owner["id"]
    query=urllib.parse.urlencode({
        "owner_id":"eq."+owner_id,
        "action_type":"in.(email,follow_up,ai_reply,proposal,financial_proposal_send,agreement,agreement_send,milestone_delivery,final_delivery,inbound_reply)",
        "select":"id,lead_id,recipient,approval_status,draft_subject,action_type,created_at",
        "order":"created_at.desc","limit":"3000"
    })
    actions=api("/rest/v1/outreach_actions?"+query,key) or []
    sent_by_recipient={}
    processed_ids=set()
    for action in actions:
        if action.get("action_type")=="inbound_reply":
            match=re.search(r"Message-ID:\s*(.+)$",action.get("draft_subject") or "")
            if match: processed_ids.add(match.group(1).strip())
        elif action.get("recipient") and action.get("approval_status") in ("pending_verification","delivered","delivery_verified"):
            address=action["recipient"].lower()
            if address not in sent_by_recipient:
                sent_by_recipient[address]=action

    leads=api("/rest/v1/leads?"+urllib.parse.urlencode({
        "owner_id":"eq."+owner_id,
        "select":"id,payload,company_name,service_need,evidence_summary,evidence_url,contact_email,lead_status",
        "limit":"3000"
    }),key) or []
    leads_by_id={row["id"]:row for row in leads}
    mail=imaplib.IMAP4_SSL(host,port,timeout=20)
    processed=replies=bounces=ignored=orders_created=approvals_created=optouts=ai_replies=ai_held=intake_replies=0
    today=datetime.now(timezone.utc).date().isoformat()
    ai_replies_today=sum(1 for a in actions if a.get("action_type")=="ai_reply"
                         and (a.get("created_at") or "").startswith(today))
    ai_reply_limit=max(0,3-ai_replies_today)
    try:
        mail.login(username,password)
        status,_=mail.select(folder)
        if status!="OK": raise RuntimeError("Could not open IMAP folder "+folder)
        # Search by the exact recipient addresses we have contacted, plus standard
        # bounce senders. This includes messages already read by the owner without
        # scanning the entire mailbox or changing its read/unread state.
        since=(datetime.now(timezone.utc)-timedelta(days=60)).strftime("%d-%b-%Y")
        search_senders=set(sent_by_recipient)|{"mailer-daemon","postmaster"}
        recent_ids=set()
        for address in search_senders:
            status,data=mail.search(None,"SINCE",since,"FROM",'"'+address+'"')
            if status!="OK": raise RuntimeError("Could not search recent mailbox messages from "+address)
            if data and data[0]: recent_ids.update(data[0].split())
        recent=sorted(recent_ids,key=lambda value:int(value))
        for msg_num in recent[-100:]:
            status,parts=mail.fetch(msg_num,"(RFC822)")
            if status!="OK" or not parts or not isinstance(parts[0],tuple): continue
            msg=email.message_from_bytes(parts[0][1])
            message_id=(msg.get("Message-ID") or "").strip()
            stable_id=message_id or ("no-id-"+str(msg_num))
            if stable_id in processed_ids:
                continue
            sender=parseaddr(msg.get("From",""))[1].lower()
            subject=decoded(msg.get("Subject",""))
            text=body_text(msg)
            combined=subject+"\n"+text
            auto_submitted=(msg.get("Auto-Submitted") or "").strip().lower()
            precedence=(msg.get("Precedence") or "").strip().lower()
            if (auto_submitted and auto_submitted!="no") or precedence in ("bulk","list","junk") or re.search(r"\b(?:out of office|automatic reply|auto.?reply|vacation responder)\b",subject,re.I):
                api("/rest/v1/outreach_actions",key,"POST",{
                    "owner_id":owner_id,"lead_id":None,"action_type":"inbound_reply",
                    "recipient":sender,"approval_status":"ignored",
                    "draft_subject":"Message-ID: "+stable_id,
                    "result_notes":"Automated mailbox response ignored to prevent reply loops."
                },"return=minimal")
                ignored+=1
                processed+=1
                continue
            is_bounce=bool(BOUNCE_RE.search(combined) or sender.startswith(("mailer-daemon","postmaster")))
            if is_bounce:
                candidates=[e.lower() for e in EMAIL_RE.findall(combined) if e.lower()!=sender]
                recipient=next((e for e in candidates if e in sent_by_recipient),"")
                if not recipient:
                    ignored+=1
                    processed+=1
                    continue
                original=sent_by_recipient[recipient]
                now=datetime.now(timezone.utc).isoformat()
                api("/rest/v1/outreach_actions?id=eq."+original["id"],key,"PATCH",{
                    "approval_status":"bounced","result_notes":"Mailbox monitor detected a delivery failure/bounce. Recipient delivery is not verified; do not retry automatically."
                },"return=minimal")
                lead=leads_by_id.get(original.get("lead_id"))
                if lead:
                    payload=lead.get("payload") if isinstance(lead.get("payload"),dict) else {}
                    payload["emailDeliveryStatus"]="bounced"
                    payload["contactVerified"]="No"
                    payload["activity"]=(payload.get("activity") if isinstance(payload.get("activity"),list) else [])+[{
                        "date":now[:10],"text":"Email bounce detected for "+recipient+"; email contact verification revoked."
                    }]
                    api("/rest/v1/leads?id=eq."+original["lead_id"],key,"PATCH",{
                        "payload":payload,"updated_at":now
                    },"return=minimal")
                event(key,owner_id,"email_bounced","bounced",
                    "Mailbox monitor detected a bounce; recipient excluded from verified delivery totals.",
                    {"lead_id":original.get("lead_id"),"recipient":recipient,"subject":subject[:180]})
                api("/rest/v1/outreach_actions",key,"POST",{
                    "owner_id":owner_id,"lead_id":original.get("lead_id"),"action_type":"inbound_reply",
                    "recipient":recipient,"approval_status":"bounced",
                    "draft_subject":"Message-ID: "+stable_id,
                    "result_notes":"Bounce notification processed; original recipient suppressed from future follow-up."
                },"return=minimal")
                bounces+=1
            else:
                original=sent_by_recipient.get(sender)
                if not original:
                    ignored+=1
                    processed+=1
                    continue
                now=datetime.now(timezone.utc).isoformat()
                api("/rest/v1/outreach_actions?id=eq."+original["id"],key,"PATCH",{
                    "approval_status":"delivery_verified",
                    "result_notes":"A genuine reply from the recipient was received. This confirms the original message reached a responding mailbox."
                },"return=minimal")
                lead=leads_by_id.get(original.get("lead_id"))
                if lead:
                    payload=lead.get("payload") if isinstance(lead.get("payload"),dict) else {}
                    payload["status"]="Replied"
                    payload["emailDeliveryStatus"]="reply_received"
                    payload["lastClientReplyAt"]=now
                    payload["activity"]=(payload.get("activity") if isinstance(payload.get("activity"),list) else [])+[{
                        "date":now[:10],"text":"Inbound email reply received from "+sender+". No automatic response was sent."
                    }]
                    api("/rest/v1/leads?id=eq."+original["lead_id"],key,"PATCH",{
                        "payload":payload,"lead_status":"replied","updated_at":now
                    },"return=minimal")
                    result=create_or_advance_order(key,owner_id,lead,sender,subject,text,now)
                    if result=="opt_out": optouts+=1
                    if result=="proposal_approval_created": orders_created+=1;approvals_created+=1
                    if result in ("agreement_approval_created","project_start_approval_created","order_close_approval_created"): approvals_created+=1
                    if result in ("reply_recorded","scope_intake_reply"):
                        account_id=os.getenv("CLOUDFLARE_AI_ACCOUNT_ID","").strip()
                        token=os.getenv("CLOUDFLARE_AI_API_TOKEN","").strip()
                        smtp_host=os.getenv("SMTP_HOST","").strip()
                        smtp_user=os.getenv("SMTP_USERNAME","").strip()
                        smtp_pass=os.getenv("SMTP_PASSWORD","").strip()
                        sender_email=os.getenv("GENIE_SENDER_EMAIL","").strip()
                        try: smtp_port=int(os.getenv("SMTP_PORT") or "587")
                        except ValueError: smtp_port=587
                        # Scope/budget intake is deterministic and does not consume the AI quota.
                        answer=(scope_intake_reply_text(lead,subject,text) if result=="scope_intake_reply"
                                else ai_reply_text(account_id,token,subject,text,lead) if ai_replies<ai_reply_limit else "")
                        if answer and all([smtp_host,smtp_user,smtp_pass,sender_email]):
                            if send_ai_reply(key,owner_id,lead,sender,subject,answer,message_id,
                                             smtp_host,smtp_port,smtp_user,smtp_pass,sender_email):
                                if result=="scope_intake_reply": intake_replies+=1
                                else: ai_replies+=1
                            else: ai_held+=1
                        else:
                            ai_held+=1
                            event(key,owner_id,"automated_client_reply","held",
                                "Client reply recorded; automated response was held safely.",
                                {"lead_id":lead["id"],"sender":sender,"subject":subject[:160],
                                 "reason":"SMTP settings or a safe automated response unavailable."})
                api("/rest/v1/outreach_actions",key,"POST",{
                    "owner_id":owner_id,"lead_id":original.get("lead_id"),"action_type":"inbound_reply",
                    "recipient":sender,"approval_status":"replied",
                    "draft_subject":"Message-ID: "+(message_id or ("no-id-"+str(msg_num))),
                    "result_notes":"Inbound reply received. Read the full reply in the mailbox. No response was sent."
                },"return=minimal")
                event(key,owner_id,"client_email_reply","replied",
                    "Inbound client reply detected; no automatic response sent.",
                    {"lead_id":original.get("lead_id"),"sender":sender,"subject":subject[:180]})
                replies+=1
            processed+=1
    finally:
        try: mail.close()
        except Exception: pass
        mail.logout()

    msg=f"Inbox monitor completed: {replies} replies, {intake_replies} automatic scope/budget intake replies, {ai_replies} bounded AI replies SMTP-accepted, {ai_held} held for review, {bounces} bounces, {optouts} opt-outs, {orders_created} proposal opportunities and {approvals_created} stage approvals; {ignored} unrelated messages ignored. SMTP acceptance is not proof of delivery."
    print(msg)
    if summary_path:
        with open(summary_path,"a",encoding="utf-8") as f: f.write("\n## Inbox monitoring\n\n"+msg+"\n")
    return 0

if __name__=="__main__":
    try: sys.exit(main())
    except Exception as exc:
        print("Inbox monitoring failed safely: "+str(exc),file=sys.stderr)
        sys.exit(1)
