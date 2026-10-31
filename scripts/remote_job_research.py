#!/usr/bin/env python3
"""Find current remote employment opportunities that match Siva's verified skill profile."""
import json, os, re, time
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError

SUPABASE_URL = "https://irpqaoooosrjhviwdddo.supabase.co"
OUT = "data/remote_jobs.json"
HEADERS = {"User-Agent": "GenieAgent-RemoteJobResearch/1.0 (public job API reader)", "Accept": "application/json"}
SKILLS = {
    "Web development": ("web developer","web development","website developer","frontend","front-end","wordpress","shopify","webflow","html","css","javascript"),
    "AI tools / chatbot": ("chatbot","ai assistant","conversational ai","prompt engineer","ai evaluator","ai trainer","llm evaluator"),
    "Automation": ("automation","workflow","no-code","zapier","make.com","n8n"),
    "Excel / data": ("excel","spreadsheet","data entry","data analyst","data annotation","data labeling","data annotator","data quality"),
    "Content / SEO": ("content writer","technical writer","seo writer","copywriter","content editor"),
    "Telugu / language QA": ("telugu","linguist","language specialist","localization","translation","proofreader"),
    "QA / testing": ("manual qa","qa tester","software tester","website tester","quality assurance"),
    "Digital design": ("graphic designer","canva designer","thumbnail designer","presentation designer")
}
SENIOR = re.compile(r"\b(senior|sr\.?|lead|principal|staff engineer|architect|engineering manager|director|head of|vp|chief)\b", re.I)
EXPERIENCE = re.compile(r"\b(?:[5-9]|[1-9][0-9])\s*\+?\s*years? (?:of )?(?:professional |commercial |relevant )?experience\b", re.I)
NON_REMOTE = re.compile(r"\b(on[- ]site|onsite|hybrid only|must be located in (?:the )?(?:us|usa|uk|canada|europe|germany|france|australia))\b", re.I)
BLOCK = re.compile(r"\b(unpaid|volunteer|commission only|equity only|internship|unpaid internship|training fee|registration fee|pay to apply)\b", re.I)

def get_json(url):
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=25) as response:
        if response.status != 200: raise RuntimeError(f"HTTP {response.status}: {url}")
        return json.loads(response.read().decode("utf-8", "replace"))

def clean_html(s):
    s = re.sub(r"(?is)<(script|style).*?>.*?</\\1>", " ", s or "")
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return re.sub(r"\\s+", " ", s).strip()

def match_skills(title, description, tags):
    hay = (title + " " + description + " " + " ".join(tags or [])).lower()
    matches=[]
    for group, terms in SKILLS.items():
        if any(term in hay for term in terms):
            matches.append(group)
    return matches

def location_eligibility(location, remote):
    loc=(location or "").strip()
    low=loc.lower()
    if any(x in low for x in ("worldwide","anywhere","global","all countries","international")):
        return "Worldwide — India eligible"
    if re.search(r"\bindia\b|india only|asia \(including india\)", low):
        return "India eligible"
    if any(x in low for x in ("united states only","usa only","us only","uk only","europe only","canada only","australia only","germany only","france only")):
        return "Not India eligible"
    if loc and not re.search(r"remote|anywhere|worldwide", low) and remote:
        return "Location restriction — verify"
    if not loc or low in {"remote","remote worldwide","remote (global)"}:
        return "Remote — country eligibility to verify"
    return "Location restriction — verify"

def normalize(source, raw, ident, title, company, location, employment, salary, desc, url, apply, posted, remote, tags):
    title=(title or "").strip()
    company=(company or "Not specified").strip()
    desc=clean_html(desc)
    tags=tags if isinstance(tags,list) else []
    matches=match_skills(title,desc,tags)
    if not matches or not title or not url: return None
    if SENIOR.search(title) or EXPERIENCE.search(desc[:12000]) or NON_REMOTE.search(title+" "+location) or BLOCK.search(title+" "+desc[:5000]): return None
    eligibility=location_eligibility(location,remote)
    if eligibility=="Not India eligible": return None
    if "Location restriction" in eligibility: return None
    if not remote and "Remote" not in (location or ""): return None
    return {
      "source_name":source,"source_job_id":str(ident or url),"title":title[:250],"company":company[:200],
      "location":(location or "Remote — country eligibility not specified")[:250],
      "employment_type":(employment or "Not specified")[:120],"salary":(salary or "Not disclosed")[:160],
      "skill_match":", ".join(matches),"eligibility_status":eligibility,
      "description":desc[:12000],"job_url":url,"apply_url":apply or url,
      "posted_at":posted if posted else None
    }

def collect():
    found={}
    errors=[]
    # Remotive: published remote roles, including contract and full-time.
    try:
        payload=get_json("https://remotive.com/api/remote-jobs?limit=500")
        for j in payload.get("jobs",[]):
            row=normalize("Remotive",j,j.get("id"),j.get("title"),j.get("company_name"),j.get("candidate_required_location"),j.get("job_type"),j.get("salary"),j.get("description"),j.get("url"),j.get("url"),j.get("publication_date"),True,j.get("tags"))
            if row: found[("Remotive",row["source_job_id"])]=row
    except Exception as e: errors.append("Remotive: "+str(e)[:180])
    # Arbeitnow: public job board API; only entries explicitly marked remote are eligible for screening.
    try:
        payload=get_json("https://www.arbeitnow.com/api/job-board-api")
        for j in payload.get("data",[]):
            remote=bool(j.get("remote"))
            row=normalize("Arbeitnow",j,j.get("slug") or j.get("url"),j.get("title"),j.get("company_name"),j.get("location"),", ".join(j.get("job_types") or []),"",j.get("description"),j.get("url"),j.get("url"),j.get("created_at"),remote,j.get("tags"))
            if row: found[("Arbeitnow",row["source_job_id"])]=row
    except Exception as e: errors.append("Arbeitnow: "+str(e)[:180])
    # RemoteOK public JSON feed.
    try:
        payload=get_json("https://remoteok.com/api")
        for j in payload:
            if not isinstance(j,dict) or not j.get("position"): continue
            location=j.get("location") or "Remote — country eligibility not specified"
            row=normalize("RemoteOK",j,j.get("id") or j.get("slug"),j.get("position"),j.get("company"),location,j.get("type")," ".join(x for x in [j.get("salary_min") and str(j.get("salary_min")),j.get("salary_max") and str(j.get("salary_max"))] if x) or "",j.get("description"),j.get("url"),j.get("apply_url") or j.get("url"),j.get("date"),True,j.get("tags"))
            if row: found[("RemoteOK",row["source_job_id"])]=row
    except Exception as e: errors.append("RemoteOK: "+str(e)[:180])
    rows=sorted(found.values(),key=lambda x:(0 if "Worldwide" in x["eligibility_status"] else 1 if "India eligible" in x["eligibility_status"] else 2, x["posted_at"] or ""),reverse=True)
    rows=rows[:250]
    return rows,errors

def owner_id(key,email):
    if not key or not email: return None
    url=SUPABASE_URL+"/auth/v1/admin/users?page=1&per_page=100"
    req=Request(url,headers={"apikey":key,"Authorization":"Bearer "+key,"Accept":"application/json"})
    with urlopen(req,timeout=20) as r: users=json.loads(r.read().decode())
    user=next((u for u in users.get("users",[]) if (u.get("email") or "").lower()==email.lower()),None)
    if not user: raise RuntimeError("GENIE_OWNER_EMAIL was not found in Supabase Auth")
    return user["id"]

def sync(rows):
    key=os.getenv("SUPABASE_SERVICE_ROLE_KEY","").strip()
    email=os.getenv("GENIE_OWNER_EMAIL","").strip()
    if not key or not email:
        print("Private job sync skipped: Supabase owner credentials are not configured.")
        return 0
    uid=owner_id(key,email)
    now=datetime.now(timezone.utc).isoformat()
    payload=[dict(x,owner_id=uid,last_seen_at=now,is_active=True,updated_at=now) for x in rows]
    headers={"apikey":key,"Authorization":"Bearer "+key,"Content-Type":"application/json","Prefer":"resolution=merge-duplicates,return=representation"}
    total=0
    for i in range(0,len(payload),50):
        req=Request(SUPABASE_URL+"/rest/v1/job_opportunities?on_conflict=owner_id,source_name,source_job_id",data=json.dumps(payload[i:i+50]).encode(),headers=headers,method="POST")
        with urlopen(req,timeout=30) as r:
            response=r.read().decode()
            total += len(json.loads(response)) if response.strip() else len(payload[i:i+50])
    return total

def main():
    os.makedirs("data",exist_ok=True)
    rows,errors=collect()
    with open(OUT,"w",encoding="utf-8") as f: json.dump({"checked_at":datetime.now(timezone.utc).isoformat(),"count":len(rows),"errors":errors,"jobs":rows},f,ensure_ascii=False,indent=2)
    synced=sync(rows)
    print(f"Remote job discovery: sources=3, matched={len(rows)}, synced={synced}, errors={len(errors)}")
    for e in errors: print("SOURCE ERROR: "+e)
    print("Remote job details stored only in the authenticated owner's private Supabase table; no applications or messages were sent.")
if __name__=="__main__": main()
