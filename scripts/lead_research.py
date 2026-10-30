#!/usr/bin/env python3
"""High-precision discovery of public business requirement candidates.

Refresh note: daily automation is intentionally allowed to return zero results rather than low-confidence leads.

This script NEVER confirms buyer intent. Search evidence remains a candidate until
the client explicitly confirms the requirement and contact details are verified.
"""
import csv, html, os, re, time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlparse, urljoin, parse_qs, unquote
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
    'need a website developer for my business',
    'seeking a freelance web developer for project',
    'small business needs website redesign',
    'looking to hire chatbot developer',
    'need help with Excel automation project',
    'seeking Power BI dashboard freelancer',
    'need Android app development company',
    'looking for automation consultant for business',
    'website development project contact business',
    'hire WordPress developer website project',
    'Shopify store development project inquiry',
    'looking for Telugu translator for business',
    'need graphic designer for company project',
    'looking for technical content writer project',
    'need help building internal business tool',
    'seeking AI integration developer business',
    'website maintenance service provider wanted',
    'CRM workflow automation project requirements',
    'Excel data cleanup freelancer needed',
    'mobile app developer project inquiry',
    '"hiring a freelance web developer" small business',
    '"paid website redesign project" small business',
    '"website development" "project budget" business',
    '"need a WordPress developer" budget',
    '"looking to hire" chatbot developer business',
    '"contract Excel automation consultant" business',
    '"paid Telugu translation project" business',
    '"hiring graphic designer" small business project',
    '"website maintenance contract" small business',
    '"request for quote" website development small business',
]
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
SKIP_DOMAINS = {
    "facebook.com","instagram.com","linkedin.com","youtube.com","x.com","twitter.com",
    "tiktok.com","pinterest.com","wikipedia.org","bing.com","microsoft.com",
    "thefreedictionary.com","merriam-webster.com","dictionary.com","thesaurus.com",
    "indeed.com","glassdoor.com","ziprecruiter.com","monster.com","simplyhired.com",
    "yelp.com","yellowpages.com","crunchbase.com","zoominfo.com","clutch.co",
    "upwork.com","fiverr.com","reddit.com","quora.com","medium.com",
    "findrfp.com","rfpdb.com","rfpmart.com","governmentbids.com","sam.gov"
}
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36", "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.8"}
INTENT = re.compile(
    r"(?:we are |we're |i am |i'm |our team is )?looking for (?:a |an |someone to |help with )?"
    r"(?:web designer|web developer|website developer|website designer|chatbot|automation consultant|"
    r"wordpress developer|shopify developer|designer|writer|technical writer|freelancer|translator|"
    r"graphic designer|app developer|software developer|excel specialist|seo specialist|"
    r"website|web app|mobile app|android app|landing page|dashboard|automation|"
    r"website redesign|logo|content writer)|"
    r"(?:we |i |our team )?(?:urgently )?need (?:a |an |someone to |help with )?"
    r"(?:chatbot|website redesign|web developer|website|web app|mobile app|android app|"
    r"automation|wordpress developer|shopify developer|designer|writer|translator|excel dashboard|logo|"
    r"landing page|spreadsheet|data cleanup|AI integration)|"
    r"(?:we are |we're |i am |i'm )?seeking (?:a |an |someone to )?"
    r"(?:web designer|web developer|chatbot|automation|designer|writer|translator|app developer|"
    r"wordpress developer|shopify developer|website builder|excel specialist)|"
    r"looking to hire (?:a |an )?(?:web|software|app|wordpress|shopify|chatbot|automation|graphic) developer|"
    r"(?:website redesign|web development|app development|chatbot development|automation) project inquiry|"
    r"developer wanted|chatbot developer wanted|automation consultant wanted|freelancer needed|"
    r"designer needed|writer needed|translator needed|website redesign project",
    re.I
)
PAID_SIGNAL = re.compile(r"\b(?:paid project|paid work|budget(?:ed)?|project budget|hiring|looking to hire|hire|contract(?:or)?|commission|compensation|rate|quote|request for quote|payment|pay for|fee|funded)\b", re.I)
UNPAID_SIGNAL = re.compile(r"\b(?:unpaid|volunteer|equity only|no budget|not paid|free work)\b", re.I)
LOW_QUALITY = re.compile(r"definition of|synonyms|thesaurus|dictionary|meaning of|jobs near|salary|course|tutorial|top 10|best companies|directory|template|examples|how to write|sample|guide|checklist|free download", re.I)

def get(url, timeout=5):
    # Retry transient blocks/timeouts before the caller moves to another engine.
    for attempt in range(2):
        try:
            req = Request(url, headers=HEADERS)
            with urlopen(req, timeout=timeout) as r:
                if r.status != 200: return ""
                return r.read(800_000).decode("utf-8", "ignore")
        except Exception as exc:
            if attempt == 1:
                print(f"Request failed after retries: {urlparse(url).netloc} ({type(exc).__name__})")
            else:
                time.sleep(1 + attempt)
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
    results=[]
    # Search engines are independent: a block or outage never ends discovery.
    providers=[
        ("Bing RSS","https://www.bing.com/search?format=rss&q="+quote(query),"rss"),
        ("DuckDuckGo HTML","https://html.duckduckgo.com/html/?q="+quote(query),"html"),
        ("Google HTML","https://www.google.com/search?num=20&q="+quote(query),"html"),
        ("Mojeek HTML","https://www.mojeek.com/search?q="+quote(query),"html"),
        ("Startpage HTML","https://www.startpage.com/sp/search?query="+quote(query),"html"),
        ("Ecosia HTML","https://www.ecosia.org/search?q="+quote(query),"html"),
    ]
    with ThreadPoolExecutor(max_workers=len(providers)) as pool:
        fetched=list(pool.map(lambda item:(item[0],item[1],item[2],get(item[1],timeout=5)),providers))
    for provider,base_url,kind,raw in fetched:
        if not raw: continue
        if kind=="rss":
            try:
                root=ET.fromstring(raw)
                results.extend((html.unescape(i.findtext("title","")),i.findtext("link",""),html.unescape(i.findtext("description","")),provider) for i in root.findall(".//item"))
            except Exception: pass
        else:
            parser=Links()
            try: parser.feed(raw)
            except Exception: continue
            for href,label in parser.links:
                target=urljoin(base_url,href)
                parsed=urlparse(target)
                if parsed.path=="/url":
                    qv=parse_qs(parsed.query).get("q") or parse_qs(parsed.query).get("url") or []
                    if qv: target=unquote(qv[0])
                if "duckduckgo.com" in host(target):
                    redirected=parse_qs(urlparse(target).query).get("uddg",[])
                    if redirected: target=unquote(redirected[0])
                if "startpage.com" in host(target):
                    redirected=parse_qs(urlparse(target).query).get("url",[])
                    if redirected and redirected[0].startswith("http"): target=unquote(redirected[0])
                if host(target) and host(target) not in {"google.com","bing.com","mojeek.com","startpage.com","ecosia.org","duckduckgo.com"}:
                    results.append((label or target,target,"",provider))
    unique=[]; seen=set()
    for title,url,snippet,provider in results:
        key=url.split("#")[0].rstrip("/")
        if key and key not in seen:
            seen.add(key); unique.append((title,url,snippet,provider))
    return unique

def is_skipped(domain):
    return not domain or domain in SKIP_DOMAINS or any(domain.endswith("."+d) for d in SKIP_DOMAINS)

def main():
    os.makedirs("data",exist_ok=True)
    old={}
    stats={"queries":0,"search_results":0,"empty_searches":0,"pages_fetched":0,"page_failures":0,"intent_pages":0,"new_candidates":0}
    if os.path.exists(OUT):
        with open(OUT,newline="",encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                key=(row.get("website","").lower().rstrip("/") or row.get("company","").lower())
                domain=host(row.get("website",""))
                if key and row.get("status")=="Research candidate" and not is_skipped(domain):
                    old[key]=row
    added=0
    checked=0
    # Exhaust the entire query bank every cycle. Do not stop after one provider
    # or one query batch returns nothing; provider fallback runs in parallel.
    query_batch=QUERIES
    max_checks_per_run=40
    discovered=[]
    for query in query_batch:
        stats["queries"] += 1
        results=search(query)
        stats["search_results"] += len(results)
        if not results: stats["empty_searches"] += 1
        discovered.extend(results)
    seen_pages=set()
    for title,url,snippet,provider in discovered:
            if checked >= max_checks_per_run or added >= 50: break
            domain=host(url)
            combined=re.sub(r"\s+"," ",title+" "+snippet)
            if not url.startswith("http") or "." not in domain or is_skipped(domain): continue
            if LOW_QUALITY.search(combined): continue
            key=url.split("#")[0].rstrip("/")
            if key in seen_pages: continue
            seen_pages.add(key)
            if key in old or any(host(v.get("website",""))==domain for v in old.values()): continue
            checked += 1
            page=get(url,timeout=4)
            if page: stats["pages_fetched"] += 1
            else: stats["page_failures"] += 1
            parser=Links()
            if page:
                try: parser.feed(page)
                except Exception: pass
            page_text=re.sub(r"\s+"," "," ".join(parser.text))
            # Search snippets alone never qualify a lead.
            intent_probe=INTENT.search(page_text)
            paid_probe=PAID_SIGNAL.search(page_text)
            on_page_intent=bool(intent_probe and paid_probe and abs(intent_probe.start()-paid_probe.start())<=2500) and not UNPAID_SIGNAL.search(page_text[:12000]) and not LOW_QUALITY.search(page_text[:12000])
            contact_url=""
            emails=set(EMAIL_RE.findall(page_text))
            for href,label in parser.links:
                candidate=urljoin(url,href)
                if host(candidate)!=domain: continue
                if any(k in (href+" "+label).lower() for k in ["contact","about"]):
                    contact_url=candidate
                    contact_html=get(candidate,timeout=3)
                    if contact_html:
                        cp=Links()
                        try: cp.feed(contact_html)
                        except Exception: pass
                        emails.update(EMAIL_RE.findall(" ".join(cp.text)))
                    break
            emails={e.lower() for e in emails if not any(x in e.lower() for x in ["example.com","domain.com","wixpress.com","sentry.io","cloudflare.com"])}
            # Email is optional at research stage; verify a business contact route before outreach.
            if not on_page_intent or not (emails or contact_url):
                continue
            stats["intent_pages"] += 1
            email=sorted(emails)[0] if emails else ""
            intent_match=INTENT.search(page_text)
            paid_match=PAID_SIGNAL.search(page_text)
            evidence_excerpt=page_text[max(0,intent_match.start()-180):min(len(page_text),intent_match.end()+300)] if intent_match else combined[:300]
            paid_excerpt=page_text[max(0,paid_match.start()-100):min(len(page_text),paid_match.end()+180)] if paid_match else ""
            row={
                "company":title[:180],"country":"Other international","contact":"",
                "contact_url":contact_url,"email":email,"paidSignal":"Yes","website":url,
                "source":url,"discovery_method":provider,"service":"Publicly stated business requirement — verify exact scope",
                "status":"Research candidate",
                "evidence":"Service requirement: "+evidence_excerpt[:350]+" | Paid-project evidence: "+paid_excerpt[:200],
                "notes":"UNVERIFIED: on-page service need, paid-project signal and public contact route found. Verify freshness, client identity, budget, scope and contact before outreach or commitment.",
                "needStage":"Needs human verification","contactVerified":"No",
                "clientNeedConfirmed":"No","needEvidenceUrl":url,"financialApproved":"No",
                "discovered_at":datetime.now(timezone.utc).isoformat()
            }
            old[key]=row;added+=1;stats["new_candidates"] += 1
            if added>=50: break
    cols=["company","country","contact","contact_url","email","paidSignal","website","source","discovery_method","service","status","evidence","notes","needStage","contactVerified","clientNeedConfirmed","needEvidenceUrl","financialApproved","discovered_at"]
    with open(OUT,"w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
        for row in old.values():w.writerow({k:row.get(k,"") for k in cols})
    print("Diagnostics: " + ", ".join(f"{k}={v}" for k,v in stats.items()))
    print(f"Saved {len(old)} unverified research candidates; {added} new pages contained on-page requirement wording. No buyer or contact is marked confirmed.")

if __name__=="__main__": main()
