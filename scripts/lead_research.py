#!/usr/bin/env python3
"""Discover public research candidates; never promote a candidate to a qualified lead automatically.

A search snippet or scraped email is not proof that a business wants to buy.
Qualified leads must be added to data/qualified_leads.csv only after the strict
requirement/contact evidence gate has been met.
"""
import csv, html, os, re, time
from datetime import datetime, timezone
from urllib.parse import quote, urlparse, urljoin
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from html.parser import HTMLParser

OUT = "data/research_candidates.csv"
QUERIES = [
    '"looking for a web developer" business project',
    '"looking for chatbot developer" business',
    '"need workflow automation" business developer',
    '"seeking SEO help" small business project',
]
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
SKIP_DOMAINS = {"facebook.com","instagram.com","linkedin.com","youtube.com","x.com","twitter.com","tiktok.com","pinterest.com","wikipedia.org","bing.com","microsoft.com"}
HEADERS = {"User-Agent": "GenieDevsLeadResearch/1.0 (public business contact research)"}

def get(url, timeout=12):
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=timeout) as r:
            if r.status != 200: return ""
            return r.read(1_000_000).decode("utf-8", "ignore")
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
    raw = get("https://www.bing.com/search?format=rss&q=" + quote(query))
    if not raw: return []
    try:
        root=ET.fromstring(raw)
        return [(html.unescape(i.findtext("title","")), i.findtext("link",""), html.unescape(i.findtext("description",""))) for i in root.findall(".//item")]
    except Exception: return []

def main():
    os.makedirs("data", exist_ok=True)
    old={}
    if os.path.exists(OUT):
        with open(OUT, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                key=(row.get("website","").lower().rstrip("/") or row.get("company","").lower())
                if key: old[key]=row
    added=0
    for query in QUERIES:
        for title, url, snippet in search(query):
            domain=host(url)
            if not url.startswith("http") or not domain or domain in SKIP_DOMAINS or "." not in domain: continue
            if any(domain.endswith("."+d) for d in SKIP_DOMAINS): continue
            key=url.split("#")[0].rstrip("/")
            if key in old or any(host(v.get("website",""))==domain for v in old.values()): continue
            page=get(url)
            parser=Links()
            if page:
                try: parser.feed(page)
                except Exception: pass
            candidates=[urljoin(url,h) for h,label in parser.links if any(w in (h+" "+label).lower() for w in ["contact","about","support"])]
            emails=set(EMAIL_RE.findall(page+" "+snippet))
            contact_url=""
            for c in candidates[:3]:
                if host(c)!=domain: continue
                contact_html=get(c)
                if contact_html:
                    emails.update(EMAIL_RE.findall(contact_html))
                    contact_url=c
                if emails: break
                time.sleep(0.3)
            emails={e.lower() for e in emails if not any(x in e.lower() for x in ["example.com","domain.com","wixpress.com","sentry.io","cloudflare.com"]) and not e.lower().endswith((".png",".jpg",".webp"))}
            email=sorted(emails)[0] if emails else ""
            row={
                "company": title[:180], "country": "Other international",
                "contact": "", "email": email, "website": url,
                "source": contact_url or url, "service": "Other / needs research",
                "status": "Unverified candidate",
                "evidence": "Unverified public search snippet only: "+re.sub(r"\s+"," ",snippet)[:400],
                "notes": "RESEARCH CANDIDATE ONLY — not a qualified lead. Search result and email are not verified proof of buyer intent. Explicit client requirement and contact verification are required before promotion. Search query: "+query,
                "needStage": "Unverified candidate", "contactVerified": "No",
                "clientNeedConfirmed": "No", "needEvidenceUrl": "", "financialApproved": "No",
                "discovered_at": datetime.now(timezone.utc).isoformat()
            }
            old[key]=row; added+=1
            if added>=30: break
            time.sleep(0.4)
        if added>=30: break
    cols=["company","country","contact","email","website","source","service","status","evidence","notes","needStage","contactVerified","clientNeedConfirmed","needEvidenceUrl","financialApproved","discovered_at"]
    with open(OUT,"w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
        for row in old.values(): w.writerow({k:row.get(k,"") for k in cols})
    print(f"Saved {len(old)} research candidates; {added} newly discovered. No candidates were promoted to qualified leads.")

if __name__=="__main__": main()
