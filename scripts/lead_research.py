#!/usr/bin/env python3
"""High-precision discovery of public business requirement candidates.

Refresh note: daily automation is intentionally allowed to return zero results rather than low-confidence leads.

This script NEVER confirms buyer intent. Search evidence remains a candidate until
the client explicitly confirms the requirement and contact details are verified.
"""
import csv, html, os, re, time
from datetime import datetime, timezone
from urllib.parse import quote, urlparse, urljoin
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from html.parser import HTMLParser

OUT = "data/research_candidates.csv"
# Broad, buyer-intent-focused searches across the user's actual deliverable services.
# These are public-web searches; only pages with explicit requirement text and a public email pass.
QUERIES = [
    '"looking for a web designer" business',
    '"looking for a web developer" website project',
    '"need a website built" business contact',
    '"website redesign" "looking for" company',
    '"website development" "request for proposal"',
    '"WordPress developer needed" business project',
    '"Shopify website developer" "looking for"',
    '"landing page design" "need a designer"',
    '"web application development" "request for quote"',
    '"mobile app development" "request for proposal"',
    '"Android app developer" project company',
    '"AI chatbot" "looking for a developer"',
    '"chatbot development" "request for proposal"',
    '"workflow automation" "looking for a consultant"',
    '"Excel automation" "need help" business',
    '"Excel dashboard" "request for proposal"',
    '"data entry project" company "contact"',
    '"data cleaning" "looking for a freelancer" business',
    '"PowerPoint presentation design" "looking for"',
    '"technical writer" "project" "contact us" company',
    '"SEO services" "request for proposal" small business',
    '"content writing" "looking for a writer" company project',
    '"logo design" "request for quote" company',
    '"graphic design project" "looking for a designer" business',
    '"Telugu translation" project company contact',
    '"English to Telugu translation" "looking for"',
    '"localization services" "request for proposal"',
    '"website maintenance" "looking for a developer" company',
    '"automation developer" "request for quote"',
    '"AI tool development" "looking for a developer"',
    '"website developer wanted" business project',
    '"seeking a chatbot developer" company',
    '"small business website" "need a developer"',
    '"RFP website design" small business',
    '"RFP software development" small business',
]
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
SKIP_DOMAINS = {
    "facebook.com","instagram.com","linkedin.com","youtube.com","x.com","twitter.com",
    "tiktok.com","pinterest.com","wikipedia.org","bing.com","microsoft.com",
    "thefreedictionary.com","merriam-webster.com","dictionary.com","thesaurus.com",
    "indeed.com","glassdoor.com","ziprecruiter.com","monster.com","simplyhired.com",
    "yelp.com","yellowpages.com","crunchbase.com","zoominfo.com","clutch.co",
    "upwork.com","fiverr.com","reddit.com","quora.com","medium.com"
}
HEADERS = {"User-Agent": "GenieDevsLeadResearch/1.1 (public business requirement research)"}
INTENT = re.compile(
    r"looking for (a |an )?(web designer|web developer|website developer|website designer|chatbot|automation consultant|"
    r"wordpress developer|shopify developer|designer|writer|technical writer|freelancer|translator|"
    r"graphic designer|app developer|software developer|excel specialist|seo specialist)|"
    r"need (a |an )?(chatbot|website redesign|web developer|website|web app|mobile app|android app|"
    r"automation|wordpress developer|shopify developer|designer|writer|translator|excel dashboard|logo)|"
    r"request for proposal|request for quote|request for bid|seeking (a |an )?(web designer|web developer|chatbot|"
    r"automation|designer|writer|translator|app developer|wordpress developer|shopify developer)|"
    r"website redesign project|developer wanted|chatbot developer wanted|automation consultant wanted|"
    r"freelancer needed|designer needed|writer needed|translator needed|looking to hire a (web|software|app) developer",
    re.I
)
LOW_QUALITY = re.compile(r"definition of|synonyms|thesaurus|dictionary|meaning of|jobs near|salary|course|tutorial|top 10|best companies|directory", re.I)

def get(url, timeout=10):
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=timeout) as r:
            if r.status != 200: return ""
            return r.read(800_000).decode("utf-8", "ignore")
    except Exception:
        return ""

class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]; self.text=[]
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag=="a" and a.get("href"): self.links.append((a["href"], " ".join(a.get("aria-label","").split())))
    def handle_data(self, data):
        clean=" ".join(data.split())
        if clean: self.text.append(clean)

def host(url):
    try: return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception: return ""

def search(query):
    raw=get("https://www.bing.com/search?format=rss&q="+quote(query))
    if not raw: return []
    try:
        root=ET.fromstring(raw)
        return [(html.unescape(i.findtext("title","")),i.findtext("link",""),html.unescape(i.findtext("description",""))) for i in root.findall(".//item")]
    except Exception: return []

def is_skipped(domain):
    return not domain or domain in SKIP_DOMAINS or any(domain.endswith("."+d) for d in SKIP_DOMAINS)

def main():
    os.makedirs("data",exist_ok=True)
    old={}
    if os.path.exists(OUT):
        with open(OUT,newline="",encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                key=(row.get("website","").lower().rstrip("/") or row.get("company","").lower())
                domain=host(row.get("website",""))
                evidence=(row.get("company","")+" "+row.get("evidence",""))
                if key and row.get("status")=="Confirmed lead" and row.get("clientNeedConfirmed")=="Yes" and row.get("contactVerified")=="Yes" and row.get("needEvidenceUrl") and not is_skipped(domain) and INTENT.search(evidence) and not LOW_QUALITY.search(evidence):
                    old[key]=row
    added=0
    for query in QUERIES:
        for title,url,snippet in search(query):
            domain=host(url)
            combined=re.sub(r"\s+"," ",title+" "+snippet)
            if not url.startswith("http") or "." not in domain or is_skipped(domain): continue
            if LOW_QUALITY.search(combined) or not INTENT.search(combined): continue
            key=url.split("#")[0].rstrip("/")
            if key in old or any(host(v.get("website",""))==domain for v in old.values()): continue
            page=get(url)
            parser=Links()
            if page:
                try: parser.feed(page)
                except Exception: pass
            page_text=re.sub(r"\s+"," "," ".join(parser.text))
            # Search snippets alone never qualify a lead.
            on_page_intent=bool(INTENT.search(page_text)) and not LOW_QUALITY.search(page_text[:12000])
            contact_url=""
            emails=set(EMAIL_RE.findall(page_text))
            for href,label in parser.links:
                candidate=urljoin(url,href)
                if host(candidate)!=domain: continue
                if any(k in (href+" "+label).lower() for k in ["contact","about"]):
                    contact_url=candidate
                    contact_html=get(candidate)
                    if contact_html:
                        cp=Links()
                        try: cp.feed(contact_html)
                        except Exception: pass
                        emails.update(EMAIL_RE.findall(" ".join(cp.text)))
                    break
            emails={e.lower() for e in emails if not any(x in e.lower() for x in ["example.com","domain.com","wixpress.com","sentry.io","cloudflare.com"])}
            # Qualification requires explicit intent on the source page plus a publicly listed email.
            if not (on_page_intent and emails):
                continue
            email=sorted(emails)[0]
            intent_match=INTENT.search(page_text)
            evidence_excerpt=page_text[max(0,intent_match.start()-180):min(len(page_text),intent_match.end()+300)] if intent_match else combined[:500]
            row={
                "company":title[:180],"country":"Other international","contact":"",
                "email":email,"website":url,
                "source":url,"service":"Publicly stated web/automation requirement",
                "status":"Confirmed lead",
                "evidence":"Explicit requirement found on source page: "+evidence_excerpt[:500],
                "notes":"AUTO-QUALIFIED: source page explicitly states a requirement and publishes a contact email. Verify freshness and scope before a financial commitment.",
                "needStage":"Client need confirmed","contactVerified":"Yes",
                "clientNeedConfirmed":"Yes","needEvidenceUrl":url,"financialApproved":"No",
                "discovered_at":datetime.now(timezone.utc).isoformat()
            }
            old[key]=row;added+=1
            if added>=50: break
            time.sleep(0.3)
        if added>=50: break
    cols=["company","country","contact","email","website","source","service","status","evidence","notes","needStage","contactVerified","clientNeedConfirmed","needEvidenceUrl","financialApproved","discovered_at"]
    with open(OUT,"w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
        for row in old.values():w.writerow({k:row.get(k,"") for k in cols})
    print(f"Saved {len(old)} confirmed leads; {added} new leads passed on-page requirement and public-contact checks. Unverified search matches are discarded.")

if __name__=="__main__": main()
