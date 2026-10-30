#!/usr/bin/env python3
"""Execute only explicitly owner-approved client order stages.

This worker never creates or approves an action. It executes only approval_requests
whose status is already 'approved'. Ambiguous sends are not retried automatically.
"""
import json, os, smtplib, sys, uuid, urllib.parse, urllib.request, urllib.error
from datetime import datetime, timezone
from email.message import EmailMessage

SUPABASE_URL="https://irpqaoooosrjhviwdddo.supabase.co"

def api(path,key,method="GET",payload=None,prefer=None):
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

def event(key,owner_id,order_id,event_type,status,summary,details):
    api("/rest/v1/automation_events",key,"POST",{
        "owner_id":owner_id,"event_type":event_type,"entity_table":"approval_requests",
        "entity_id":order_id,"event_status":status,"summary":summary,"details":details
    },"return=minimal")

def get_one(path,key):
    rows=api(path,key) or []
    return rows[0] if rows else None

def clean_header(value):
    return " ".join(str(value or "").replace("\r"," ").replace("\n"," ").split())[:180]

def finance_ready(finance):
    if not finance or finance.get("approval_status")!="approved" or not finance.get("approved_by") or not finance.get("approved_at"):
        return False,"Owner financial review is not approved."
    revenue=float(finance.get("proposed_revenue") or 0)
    costs=float(finance.get("estimated_costs") or 0)
    net=float(finance.get("estimated_net_profit") if finance.get("estimated_net_profit") is not None else revenue-costs)
    if revenue<=0: return False,"Approved proposal needs a positive revenue amount."
    if net<0: return False,"Negative estimated net profit blocks proposal sending."
    if not (finance.get("scope_summary") or "").strip(): return False,"Financial scope is missing."
    if not (finance.get("payment_terms") or "").strip(): return False,"Payment terms are missing."
    if not (finance.get("evidence_url") or "").strip(): return False,"Current cost/pricing evidence URL is missing."
    return True,""

def send_stage_email(key,owner_id,request,order,lead,smtp):
    host,port,user,password,sender=smtp
    recipient=(lead.get("contact_email") or "").strip()
    if not recipient: raise RuntimeError("Verified client email is missing.")
    subject=clean_header(request.get("document_subject") or request.get("title"))
    body=(request.get("document_body") or "").strip()
    if not body: raise RuntimeError("Owner-reviewed document body is empty.")
    lower=body.lower()
    placeholders=("enter the owner-approved amount","enter verified terms","confirm exact deliverables",
                  "confirm against the approved","confirm the approved deposit","confirm milestones",
                  "timeline: confirm","to be confirmed","draft for owner review")
    if any(x in lower for x in placeholders):
        raise RuntimeError("Draft still contains unresolved placeholders; edit and approve the complete content first.")
    url=(request.get("document_url") or "").strip()
    if request.get("stage") in ("milestone_delivery","final_delivery") and not url and "http://" not in body and "https://" not in body:
        raise RuntimeError("Milestone/final delivery requires a verified file or delivery URL.")
    if url and url not in body: body+="\n\nDelivery link: "+url
    msg=EmailMessage()
    msg["From"]=sender
    msg["To"]=recipient
    msg["Reply-To"]=sender
    msg["Subject"]=subject
    msg.set_content(body)
    action_id=str(uuid.uuid4())
    api("/rest/v1/outreach_actions",key,"POST",[{
        "id":action_id,"owner_id":owner_id,"lead_id":request["lead_id"],
        "action_type":request["stage"],"draft_subject":subject,"draft_body":body,
        "recipient":recipient,"approval_status":"pending",
        "result_notes":"Owner explicitly approved this exact stage document. SMTP delivery is not independently verified."
    }],"return=minimal")
    try:
        with smtplib.SMTP(host,port,timeout=25) as server:
            server.starttls()
            server.login(user,password)
            server.send_message(msg)
    except Exception as exc:
        api("/rest/v1/outreach_actions?id=eq."+action_id,key,"PATCH",{
            "approval_status":"failed","result_notes":"SMTP stage send failed: "+str(exc)[:350]
        },"return=minimal")
        raise
    now=datetime.now(timezone.utc).isoformat()
    api("/rest/v1/outreach_actions?id=eq."+action_id,key,"PATCH",{
        "approval_status":"pending_verification","executed_at":now,
        "result_notes":"SMTP accepted owner-approved stage message. Recipient delivery remains unverified until reply/bounce monitoring."
    },"return=minimal")
    return action_id,now

def main():
    key=os.getenv("SUPABASE_SERVICE_ROLE_KEY","").strip()
    owner_email=os.getenv("GENIE_OWNER_EMAIL","").strip().lower()
    host=os.getenv("SMTP_HOST","").strip()
    port=int(os.getenv("SMTP_PORT") or "587")
    user=os.getenv("SMTP_USERNAME","").strip()
    password=os.getenv("SMTP_PASSWORD","").strip()
    sender=os.getenv("GENIE_SENDER_EMAIL","").strip()
    summary_path=os.getenv("GITHUB_STEP_SUMMARY")
    if not all([key,owner_email]):
        print("Approved-stage executor skipped: owner/Supabase configuration is missing.")
        return 0
    users=api("/auth/v1/admin/users?page=1&per_page=100",key) or {}
    owner=next((u for u in users.get("users",[]) if (u.get("email") or "").lower()==owner_email),None)
    if not owner: raise RuntimeError("Owner email not found in Supabase Auth.")
    owner_id=owner["id"]
    q=urllib.parse.urlencode({
        "owner_id":"eq."+owner_id,"status":"eq.approved","select":"*",
        "order":"requested_at.asc","limit":"100"
    })
    requests=api("/rest/v1/approval_requests?"+q,key) or []
    executed=blocked=failed=0
    for req in requests:
        stage=req.get("stage")
        order=get_one("/rest/v1/client_orders?id=eq."+req["order_id"]+"&owner_id=eq."+owner_id+"&select=*",key)
        lead=get_one("/rest/v1/leads?id=eq."+req["lead_id"]+"&owner_id=eq."+owner_id+"&select=*",key)
        if not order or not lead:
            blocked+=1
            continue
        finance=get_one("/rest/v1/financial_approvals?"+urllib.parse.urlencode({
            "owner_id":"eq."+owner_id,"lead_id":"eq."+req["lead_id"],"select":"*","limit":"1"
        }),key)
        if stage in ("financial_proposal_send","agreement_send"):
            ready,reason=finance_ready(finance)
            if not ready:
                blocked+=1
                api("/rest/v1/approval_requests?id=eq."+req["id"],key,"PATCH",{
                    "result_notes":"Approved by owner, but execution is blocked: "+reason
                },"return=minimal")
                continue
        if stage=="financial_proposal_send" and order.get("order_status") not in ("awaiting_financial_approval","financial_proposal_approved"):
            blocked+=1; continue
        if stage=="agreement_send" and (order.get("order_status")!="awaiting_agreement_approval" or not order.get("client_accepted_at")):
            blocked+=1; continue
        if stage=="project_start" and order.get("order_status")!="awaiting_project_start_approval":
            blocked+=1; continue
        if stage=="milestone_delivery" and order.get("order_status")!="in_progress":
            blocked+=1; continue
        if stage=="final_delivery" and order.get("order_status")!="in_progress":
            blocked+=1; continue
        if stage=="order_close" and order.get("order_status")!="awaiting_order_close_approval":
            blocked+=1; continue
        if stage not in ("financial_proposal_send","agreement_send","project_start","milestone_delivery","final_delivery","order_close"):
            blocked+=1; continue

        # Lock before external side effects. If a run is interrupted mid-send, it will not resend.
        api("/rest/v1/approval_requests?id=eq."+req["id"]+"&status=eq.approved",key,"PATCH",{
            "status":"executing","result_notes":"Owner approval received; execution started."
        },"return=minimal")
        try:
            now=datetime.now(timezone.utc).isoformat()
            action_id=None
            if stage in ("financial_proposal_send","agreement_send","milestone_delivery","final_delivery"):
                if not all([host,user,password,sender]):
                    raise RuntimeError("SMTP settings are missing; no client message sent.")
                action_id,now=send_stage_email(key,owner_id,req,order,lead,(host,port,user,password,sender))
            if stage=="financial_proposal_send":
                order_patch={"order_status":"financial_proposal_sent","proposal_sent_at":now}
                lead_payload=lead.get("payload") if isinstance(lead.get("payload"),dict) else {}
                lead_payload["status"]="Proposal sent"
                lead_payload["proposalSentAt"]=now
                api("/rest/v1/leads?id=eq."+lead["id"],key,"PATCH",{
                    "payload":lead_payload,"lead_status":"proposal","updated_at":now
                },"return=minimal")
            elif stage=="agreement_send":
                order_patch={"order_status":"agreement_sent","agreement_sent_at":now}
            elif stage=="project_start":
                order_patch={"order_status":"in_progress","project_started_at":now}
            elif stage=="milestone_delivery":
                order_patch={"order_status":"in_progress"}
            elif stage=="final_delivery":
                order_patch={"order_status":"final_delivery_sent","final_delivered_at":now}
            else:
                order_patch={"order_status":"completed","completed_at":now}
            api("/rest/v1/client_orders?id=eq."+order["id"],key,"PATCH",order_patch,"return=minimal")
            api("/rest/v1/approval_requests?id=eq."+req["id"],key,"PATCH",{
                "status":"executed","executed_at":now,"outreach_action_id":action_id,
                "result_notes":"Owner-approved stage executed successfully. "+("SMTP accepted the message; delivery remains unverified." if action_id else "Database stage transition completed.")
            },"return=minimal")
            event(key,owner_id,order["id"],"approved_stage_executed","executed",
                  "Owner-approved client order stage executed: "+stage,
                  {"lead_id":req["lead_id"],"approval_request_id":req["id"],"outreach_action_id":action_id})
            executed+=1
        except Exception as exc:
            api("/rest/v1/approval_requests?id=eq."+req["id"],key,"PATCH",{
                "status":"failed","result_notes":"Execution failed; automatic retry is disabled to prevent duplicate external actions. Review before retry: "+str(exc)[:500]
            },"return=minimal")
            event(key,owner_id,order["id"],"approved_stage_failed","failed",
                  "Owner-approved stage failed; manual review required.",
                  {"lead_id":req["lead_id"],"approval_request_id":req["id"],"error":str(exc)[:500]})
            failed+=1
    msg=f"Approved-stage executor: {executed} executed, {blocked} blocked pending required details/state, {failed} failed and held for manual review."
    print(msg)
    if summary_path:
        with open(summary_path,"a",encoding="utf-8") as f: f.write("\n## Owner-approved order stages\n\n"+msg+"\n")
    return 0

if __name__=="__main__":
    try: sys.exit(main())
    except Exception as exc:
        print("Approved-stage executor failed safely: "+str(exc),file=sys.stderr)
        sys.exit(1)
