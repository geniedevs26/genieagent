#!/usr/bin/env python3
"""Daily public-web lead discovery for GenieDevs.
Uses Bing's public RSS search results, visits public business pages, and records only
public business contact details. Review every lead before outreach.
"""
import csv, html, json, os, re, time
from datetime import datetime, timezone
from urllib.parse import quote, urlparse, urljoin
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from html.parser import HTMLParser

OUT = "data/auto_leads.csv"
QUERIES = [
    '"contact us" small business website redesign',
    '"contact" "website needs" small business',
    '"contact us" small business chatbot',
    '"contact us" local business outdated website',
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
        super().__init__(); self.links=[]; self.text=[]
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag=="a" and a.get("href"): self.links.append((a["href"], " ".join(a.get("aria-label","").split())))
    def handle_data(self, data):
        if data.strip(): self.text.append(data.strip())

def host(url):
    try: return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception: return ""

def search(query):
    url = "https://www.bing.com/search?format=rss&q=" + quote(query)
    raw = get(url)
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
            candidates=[urljoin(url,h) for h,_ in parser.links if any(w in (h+" "+_).lower() for w in ["contact","about","support"])]
            emails=set(EMAIL_RE.findall(page+" "+snippet))
            contact_url=""
            for c in candidates[:3]:
                if host(c)!=domain: continue
                contact_html=get(c)
                if contact_html:
                    emails.update(EMAIL_RE.findall(contact_html))
                    contact_url=c
                if emails: break
                time.sleep(0.4)
            emails={e.lower() for e in emails if not any(x in e.lower() for x in ["example.com","domain.com","wixpress.com","sentry.io","cloudflare.com"]) and not e.lower().endswith((".png",".jpg",".webp"))}
            email=sorted(emails)[0] if emails else ""
            # Search result alone is not proof of a defect; require manual verification.
            row={
                "company": title[:180], "country": "Other international",
                "contact": "", "email": email, "website": url,
                "source": contact_url or url, "service": "Website / landing page",
                "status": "Researching",
                "evidence": "Search result: "+re.sub(r"\s+"," ",snippet)[:400]+" — verify the business and observation manually before outreach.",
                "notes": "Auto-discovered from public Bing RSS search. Email may be absent or require verification. Search query: "+query,
                "discovered_at": datetime.now(timezone.utc).isoformat()
            }
            old[key]=row; added+=1
            if added>=30: break
            time.sleep(0.5)
        if added>=30: break
    cols=["company","country","contact","email","website","source","service","status","evidence","notes","discovered_at"]
    with open(OUT,"w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
        for row in old.values(): w.writerow({k:row.get(k,"") for k in cols})
    print(f"Saved {len(old)} unique candidate leads; {added} newly discovered this run to {OUT}")

if __name__=="__main__": main()
