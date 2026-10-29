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
QUERIES = [
    '"looking for a web designer" business',
    '"need a chatbot" company',
    '"request for proposal" website development company',
    '"seeking workflow automation" business',
    '"website redesign project" "contact us" company',
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
    r"looking for (a |an )?(web designer|web developer|website developer|chatbot|automation consultant)|"
    r"need (a |an )?(chatbot|website redesign|web developer|automation)|"
    r"request for proposal|request for quote|seeking (a |an )?(web designer|web developer|chatbot|automation)|"
    r"website redesign project|developer wanted|chatbot developer wanted|automation consultant wanted",
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
        super().__init__(); self.links=[]
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag=="a" and a.get("href"): self.links.append((a["href"], " ".join(a.get("aria-label","").split())))

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
                if key and row.get("status")=="Unverified candidate" and not is_skipped(domain) and INTENT.search(evidence) and not LOW_QUALITY.search(evidence):
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
            contact_url=""
            emails=set()
            for href,label in parser.links:
                candidate=urljoin(url,href)
                if host(candidate)!=domain: continue
                if any(k in (href+" "+label).lower() for k in ["contact","about"]):
                    contact_url=candidate
                    contact_html=get(candidate)
                    if contact_html: emails.update(EMAIL_RE.findall(contact_html))
                    break
            # Only emails from the business's own pages are recorded; search snippets are not trusted as contact verification.
            emails={e.lower() for e in emails if not any(x in e.lower() for x in ["example.com","domain.com","wixpress.com","sentry.io","cloudflare.com"])}
            row={
                "company":title[:180],"country":"Other international","contact":"",
                "email":sorted(emails)[0] if emails else "","website":url,
                "source":contact_url or url,"service":"Other / needs confirmation",
                "status":"Unverified candidate",
                "evidence":"Possible requirement phrase in public search result: "+combined[:500],
                "notes":"UNVERIFIED CANDIDATE — phrase match only. This is not proof of current buyer intent. Confirm the exact requirement with the client and verify contact before qualification.",
                "needStage":"Unverified candidate","contactVerified":"No",
                "clientNeedConfirmed":"No","needEvidenceUrl":"","financialApproved":"No",
                "discovered_at":datetime.now(timezone.utc).isoformat()
            }
            old[key]=row;added+=1
            if added>=20: break
            time.sleep(0.3)
        if added>=20: break
    cols=["company","country","contact","email","website","source","service","status","evidence","notes","needStage","contactVerified","clientNeedConfirmed","needEvidenceUrl","financialApproved","discovered_at"]
    with open(OUT,"w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
        for row in old.values():w.writerow({k:row.get(k,"") for k in cols})
    print(f"Saved {len(old)} unverified candidates; {added} new phrase-matched candidates. No leads were qualified automatically.")

if __name__=="__main__": main()
