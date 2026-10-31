#!/usr/bin/env python3
"""Global multi-source discovery of explicit paid project requests.

A lead qualifies only when a buyer-authored source shows a concrete service need, paid intent,
no unpaid/job/employer signals, and a usable public contact route (business email/contact form
or an active buyer post that accepts replies). This is not a promise of client acceptance or income.
"""
import csv, html, json, os, re, time
from urllib.error import HTTPError
import urllib.parse
from datetime import datetime, timezone, timedelta
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
    'site:reddit.com/r/forhire [Hiring] web developer paid project',
    'site:reddit.com/r/forhire [Hiring] website designer budget',
    'site:reddit.com/r/forhire [Hiring] chatbot developer',
    'site:reddit.com/r/forhire [Hiring] automation developer',
    'site:reddit.com/r/forhire [Hiring] Excel automation',
    'site:reddit.com/r/forhire [Hiring] Android app developer',
    'site:reddit.com/r/forhire [Hiring] graphic designer business',
    'site:reddit.com/r/forhire [Hiring] technical writer paid',
    'site:reddit.com/r/forhire [Hiring] Telugu translator',
    'site:reddit.com/r/FreelanceIndia hiring website developer paid',
    'site:reddit.com/r/Entrepreneur looking for website developer budget',
    'site:reddit.com/r/smallbusiness need website developer paid',
    'site:reddit.com/r/startups hiring web developer project budget',
    'site:reddit.com/r/Wordpress hiring developer website paid',
    'site:reddit.com/r/shopify looking for Shopify developer paid',
    'site:reddit.com/r/automation hiring workflow automation consultant',
    'site:reddit.com/r/excel hiring Excel automation freelancer',
    'site:reddit.com/r/androiddev hiring Android app developer contract',
    'site:reddit.com/r/forhire "paid" "website redesign" hiring',
    'site:reddit.com/r/forhire "budget" "web app" hiring',
]
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
REDDIT_FEEDS = ("forhire-web","forhire-website","forhire-chatbot","forhire-automation","forhire-excel","freelanceindia-web","freelanceindia-chatbot","done-dirt-cheap-web","wordpress-jobs","design-jobs-web","android-jobs-app")
REDDIT_POST_CACHE = {}
REDDIT_ADULT_RE = re.compile(r"\b(?:nsfw|adult content|onlyfans|porn|escort|sex work|18\+)\b", re.I)
SKIP_DOMAINS = {
    "facebook.com","instagram.com","linkedin.com","youtube.com","x.com","twitter.com",
    "tiktok.com","pinterest.com","wikipedia.org","bing.com","microsoft.com",
    "thefreedictionary.com","merriam-webster.com","dictionary.com","thesaurus.com",
    "indeed.com","glassdoor.com","ziprecruiter.com","monster.com","simplyhired.com",
    "yelp.com","yellowpages.com","crunchbase.com","zoominfo.com","clutch.co",
    "upwork.com","fiverr.com","quora.com","medium.com",
    "findrfp.com","rfpdb.com","rfpmart.com","governmentbids.com","sam.gov","hubspot.com",
    "freelancer.com","peopleperhour.com","guru.com","workana.com","toptal.com","bark.com","thumbtack.com",
    "99designs.com","designcrowd.com","truelancer.com","remoteok.com","weworkremotely.com","wellfound.com",
    "careerbuilder.com","dice.com","jooble.org","naukri.com","foundit.in","shine.com","timesjobs.com",
    "seek.com.au","reed.co.uk","totaljobs.com","cv-library.co.uk","adzuna.com","jobstreet.com","monster.com"
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
    r"(?:we are |we're |i am |i'm )?hiring (?:a |an )?(?:web|software|app|wordpress|shopify|chatbot|automation|graphic) developer|"
    r"(?:website redesign|web development|app development|chatbot development|automation) project inquiry|"
    r"developer wanted|chatbot developer wanted|automation consultant wanted|freelancer needed|"
    r"designer needed|writer needed|translator needed|website redesign project",
    re.I
)
PAID_SIGNAL = re.compile(r"\b(?:paid project|paid work|budget(?:ed)?|project budget|hiring|looking to hire|hire|contract(?:or)?|commission|compensation|rate|quote|request for quote|payment|pay for|fee|funded)\b", re.I)
UNPAID_SIGNAL = re.compile(r"\b(?:unpaid|volunteer|equity only|no budget|not paid|free work)\b", re.I)
LOW_QUALITY = re.compile(r"definition of|synonyms|thesaurus|dictionary|meaning of|jobs near|salary|course|tutorial|top 10|best companies|directory|template|examples|how to write|sample|guide|checklist|free download|what is an? |how to create|how to build|step-by-step|ultimate guide|rfp template|proposal template|blog post|case study|\bblog\b|\barticle\b|\bresources?\b|\bwhitepaper\b|\bwebinar\b|\bpress release\b|\bportfolio\b|\bjob description\b|\bcareers?\b|\bhow it works\b", re.I)
NON_BUYER_PATH = re.compile(r"/(?:blog|articles?|resources?|learn|academy|guides?|templates?|examples?|news|press|careers?|jobs?|vacancies|positions)(?:/|$)", re.I)
JOB_LISTING = re.compile(r"\b(?:apply now|submit (?:your )?resume|job description|employment type|salary range|career opportunity|job opening|vacancy|job board|job listings|remote job|position available|apply for this job|full[- ]time position|part[- ]time position)\b", re.I)
DIRECT_INTENT = re.compile(r"\b(?:we(?:'re| are)?|our team|our company|our business|i(?:'m| am)|my company|my business)\b.{0,500}\b(?:looking for|need|seeking|hiring|want to hire|request(?:ing)? a quote|need help with)\b", re.I | re.S)
SUPABASE_URL = "https://irpqaoooosrjhviwdddo.supabase.co"

def get(url, timeout=5, attempts=2):
    # Search engines are tried independently; search calls can disable retries
    # because the other providers are already running in parallel.
    for attempt in range(attempts):
        try:
            req = Request(url, headers=HEADERS)
            with urlopen(req, timeout=timeout) as r:
                if r.status != 200: return ""
                return r.read(800_000).decode("utf-8", "ignore")
        except Exception as exc:
            if attempt == attempts - 1:
                print(f"Request failed after {attempts} attempt(s): {urlparse(url).netloc} ({type(exc).__name__})")
            else:
                time.sleep(1 + attempt)
    return ""

class Links(HTMLParser):
    """Extract visible page text only; never treat JavaScript/CSS as buyer evidence."""
    HIDDEN_TAGS = {"script", "style", "noscript", "svg", "template", "iframe"}
    def __init__(self):
        super().__init__(); self.links=[]; self.text=[]; self.hidden_depth=0
    def handle_starttag(self, tag, attrs):
        if tag in self.HIDDEN_TAGS: self.hidden_depth += 1
        a=dict(attrs)
        if not self.hidden_depth and tag=="a" and a.get("href"):
            self.links.append((a["href"], " ".join(a.get("aria-label","").split())))
    def handle_endtag(self, tag):
        if tag in self.HIDDEN_TAGS: self.hidden_depth=max(0,self.hidden_depth-1)
    def handle_data(self, data):
        if self.hidden_depth: return
        clean=" ".join(data.split())
        if clean: self.text.append(clean)

def extract_public_phone(text, links):
    """Extract a plausible phone number visibly published on the business page."""
    values=[urllib.parse.unquote(href[4:].split("?")[0]) for href,label in links if href.lower().startswith("tel:")]
    values.extend(re.findall(r"(?<!\w)(?:\+?\d[\d\s()./-]{6,}\d)(?!\w)", text or ""))
    for value in values:
        digits=re.sub(r"\D","",value)
        if 8 <= len(digits) <= 15:
            return ("+" if value.strip().startswith("+") else "")+digits
    return ""

def host(url):
    try: return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception: return ""

def discover_reddit_requests():
    """Read allowlisted public Reddit RSS feeds directly; no third-party CORS proxy."""
    found=[]
    atom="{http://www.w3.org/2005/Atom}"
    checked=0
    failures=0
    for feed_key in REDDIT_FEEDS:
        subreddit, query = {
            "forhire-web": ("forhire", "title:Hiring web developer"),
            "forhire-website": ("forhire", "title:Hiring website"),
            "forhire-chatbot": ("forhire", "title:Hiring chatbot"),
            "forhire-automation": ("forhire", "title:Hiring automation"),
            "forhire-excel": ("forhire", "title:Hiring Excel"),
            "freelanceindia-web": ("FreelanceIndia", "title:Hiring website developer"),
            "freelanceindia-chatbot": ("FreelanceIndia", "title:Hiring chatbot"),
            "done-dirt-cheap-web": ("DoneDirtCheap", "title:Hiring website"),
            "wordpress-jobs": ("WordpressJobs", "title:Hiring WordPress"),
            "design-jobs-web": ("DesignJobs", "title:Hiring website design"),
            "android-jobs-app": ("AndroidJobs", "title:Hiring Android app"),
        }[feed_key]
        feed_url=f"https://www.reddit.com/r/{subreddit}/search.rss?q={urllib.parse.quote(query)}&restrict_sr=1&sort=new&t=month"
        raw=get(feed_url,timeout=10,attempts=1)
        checked+=1
        if not raw:
            failures+=1
            continue
        try: root=ET.fromstring(raw)
        except ET.ParseError:
            failures+=1
            continue
        for entry in root.findall(atom+"entry"):
            title=(entry.findtext(atom+"title") or "").strip()
            if not re.search(r"^\s*(?:\[\s*HIRING\s*\]|🔴\s*HIRING:|HIRING\b)",title,re.I): continue
            link_el=next((x for x in entry.findall(atom+"link") if x.attrib.get("rel","alternate")=="alternate"),None)
            link=(link_el.attrib.get("href","") if link_el is not None else "")
            if not link.startswith("https://www.reddit.com/"): continue
            body_html=html.unescape(entry.findtext(atom+"content") or "")
            parser=Links()
            try: parser.feed(body_html)
            except Exception: continue
            body_text=" ".join(parser.text)
            combined=re.sub(r"\s+"," ",title+" "+body_text)
            if not body_text or REDDIT_ADULT_RE.search(combined): continue
            if not INTENT.search(combined) or not PAID_SIGNAL.search(combined): continue
            if UNPAID_SIGNAL.search(combined) or LOW_QUALITY.search(combined) or JOB_LISTING.search(combined): continue
            page="<html><head><title>"+html.escape(title)+"</title></head><body><main>"+body_html+"</main></body></html>"
            key=link.split("?")[0].rstrip("/")
            REDDIT_POST_CACHE[key]=(page, "Public buyer post found in Reddit RSS; verify thread remains open before outreach")
            found.append((title,link,body_text,"Reddit buyer RSS "+feed_key))
    print(f"Reddit RSS diagnostics: feeds_checked={checked}, feed_failures={failures}, buyer_posts_matched={len(found)}")
    return found

def fetch_reddit_post(url):
    """Return buyer-authored Reddit text from RSS cache, with JSON as a fallback."""
    clean=url.split("?")[0].rstrip("/")
    if not host(clean).endswith("reddit.com"):
        return "", False, ""
    if clean in REDDIT_POST_CACHE:
        page,method=REDDIT_POST_CACHE[clean]
        return page,True,method
    raw=get(clean+".json?raw_json=1",timeout=8,attempts=1)
    if not raw: return "", False, ""
    try:
        data=json.loads(raw)
        post=data[0]["data"]["children"][0]["data"]
    except (ValueError,KeyError,IndexError,TypeError):
        return "", False, ""
    author=(post.get("author") or "").strip()
    body=(post.get("selftext") or "").strip()
    title=(post.get("title") or "").strip()
    if not author or author in {"[deleted]","[removed]"} or post.get("removed_by_category") or post.get("locked") or post.get("archived"):
        return "", False, ""
    if not body or body in {"[deleted]","[removed]"}:
        return "", False, ""
    page="<html><head><title>"+html.escape(title)+"</title></head><body><main>"+html.escape(title+" "+body)+"</main></body></html>"
    return page, True, "Active buyer-authored Reddit post; public reply route verified"


SOCIAL_PAGE_CACHE = {}

def discover_social_requests():
    """Search public no-key APIs for buyer-authored posts with an existing reply path."""
    found=[]
    queries=[
        "looking for web developer", "need website developer", "hiring web developer budget",
        "need WordPress developer", "looking for Shopify developer", "need chatbot developer",
        "looking for automation developer", "paid Excel project", "need Android app developer",
        "looking for graphic designer project", "need Telugu translator", "website redesign budget",
        "looking for technical writer", "need landing page designer",
    ]
    for query in queries:
        bsky_url="https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts?"+urllib.parse.urlencode({"q":query,"limit":30,"sort":"latest"})
        raw=get(bsky_url,timeout=12,attempts=1)
        if raw:
            try: posts=json.loads(raw).get("posts",[])
            except (ValueError,AttributeError): posts=[]
            for item in posts:
                post=item.get("post") or {}
                record=post.get("record") or {}
                author=post.get("author") or {}
                body=(record.get("text") or "").strip()
                handle=(author.get("handle") or "").strip()
                uri=post.get("uri") or ""
                if not body or not handle or not uri or int(post.get("replyCount") or 0)<1: continue
                url=f"https://bsky.app/profile/{handle}/post/{uri.rsplit('/',1)[-1]}"
                page="<html><head><title>"+html.escape(handle)+" — public buyer request</title></head><body><main>"+html.escape(body)+"</main></body></html>"
                SOCIAL_PAGE_CACHE[url]=(page,True,"Public Bluesky post with existing replies; public reply route")
                found.append(("Bluesky buyer post",url,body[:700],"Bluesky public search API"))
        hn_url="https://hn.algolia.com/api/v1/search_by_date?"+urllib.parse.urlencode({"query":query,"tags":"comment","hitsPerPage":30})
        raw=get(hn_url,timeout=12,attempts=1)
        if raw:
            try: hits=json.loads(raw).get("hits",[])
            except (ValueError,AttributeError): hits=[]
            for hit in hits:
                body=html.unescape(re.sub(r"<[^>]+>"," ",hit.get("comment_text") or ""))
                body=re.sub(r"\s+"," ",body).strip()
                author=(hit.get("author") or "").strip()
                item_id=str(hit.get("objectID") or "")
                if not body or not author or not item_id: continue
                url="https://news.ycombinator.com/item?id="+item_id
                page="<html><head><title>Hacker News public request</title></head><body><main>"+html.escape(body)+"</main></body></html>"
                SOCIAL_PAGE_CACHE[url]=(page,True,"Public Hacker News comment with a reply thread")
                found.append(("Hacker News buyer comment",url,body[:700],"Hacker News Algolia public API"))
    unique={item[1]:item for item in found}
    return list(unique.values())

def search(query, page_offset=0):
    results=[]
    page_offset=max(0,int(page_offset))
    bing_first=page_offset*10+1
    ddg_start=page_offset*30
    google_start=page_offset*10
    page_num=page_offset+1
    # Search engines are independent: a block or outage never ends discovery.
    providers=[
        ("Bing RSS","https://www.bing.com/search?format=rss&count=10&first="+str(bing_first)+"&q="+quote(query),"rss"),
        ("DuckDuckGo HTML","https://html.duckduckgo.com/html/?s="+str(ddg_start)+"&q="+quote(query),"html"),
        ("Google HTML","https://www.google.com/search?num=20&start="+str(google_start)+"&q="+quote(query),"html"),
        ("Mojeek HTML","https://www.mojeek.com/search?page="+str(page_num)+"&q="+quote(query),"html"),
        ("Startpage HTML","https://www.startpage.com/sp/search?page="+str(page_num)+"&query="+quote(query),"html"),
        ("Ecosia HTML","https://www.ecosia.org/search?p="+str(page_num)+"&q="+quote(query),"html"),
    ]
    with ThreadPoolExecutor(max_workers=len(providers)) as pool:
        fetched=list(pool.map(lambda item:(item[0],item[1],item[2],get(item[1],timeout=5,attempts=1)),providers))
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


def api(path, key, method="GET", payload=None, prefer=None):
    headers={"apikey":key,"Authorization":"Bearer "+key,"Accept":"application/json"}
    data=None
    if payload is not None:
        data=json.dumps(payload).encode("utf-8")
        headers["Content-Type"]="application/json"
    if prefer: headers["Prefer"]=prefer
    req=Request(SUPABASE_URL+path,data=data,headers=headers,method=method)
    try:
        with urlopen(req,timeout=25) as response:
            raw=response.read().decode("utf-8","replace")
            return json.loads(raw) if raw.strip() else None
    except HTTPError as exc:
        detail=exc.read().decode("utf-8","replace")[:1200]
        raise RuntimeError(f"Supabase API {method} {path.split('?')[0]} failed: HTTP {exc.code}: {detail}") from exc

def owner_context():
    key=os.getenv("SUPABASE_SERVICE_ROLE_KEY","").strip()
    email=os.getenv("GENIE_OWNER_EMAIL","").strip().lower()
    if not key or not email: return key,""
    users=api("/auth/v1/admin/users?page=1&per_page=100",key) or {}
    owner=next((u for u in users.get("users",[]) if (u.get("email") or "").lower()==email),None)
    if not owner: raise RuntimeError("GENIE_OWNER_EMAIL was not found in Supabase Auth; research cursor cannot be persisted.")
    return key,owner["id"]

def load_seen_urls(key, owner_id):
    if not key or not owner_id: return set()
    q=urllib.parse.urlencode({"owner_id":"eq."+owner_id,"select":"url","next_check_at":"gt."+datetime.now(timezone.utc).isoformat(),"limit":"10000"})
    rows=api("/rest/v1/research_pages?"+q,key) or []
    return {str(x.get("url","")).split("#")[0].rstrip("/") for x in rows if x.get("url")}

def save_seen_pages(key, records):
    if not key or not records: return
    # PostgREST bulk upserts require every object in one JSON array to have
    # exactly the same keys. Do not drop null-valued keys row-by-row.
    columns=("owner_id","url","domain","source_name","outcome",
             "evidence_excerpt","checked_at","next_check_at")
    clean=[{column: row.get(column) for column in columns} for row in records]
    for start in range(0,len(clean),50):
        batch=clean[start:start+50]
        try:
            api("/rest/v1/research_pages?on_conflict=owner_id,url",key,"POST",batch,
                "resolution=merge-duplicates,return=minimal")
        except RuntimeError as exc:
            # Preserve the rest of the research run if a single bad row is
            # rejected; isolate it and continue storing valid cursor records.
            if len(batch)==1:
                print("Research cursor row rejected; continuing safely: "+str(exc)[:300])
                continue
            midpoint=len(batch)//2
            for subset in (batch[:midpoint],batch[midpoint:]):
                try:
                    api("/rest/v1/research_pages?on_conflict=owner_id,url",key,"POST",subset,
                        "resolution=merge-duplicates,return=minimal")
                except RuntimeError:
                    for row in subset:
                        try:
                            api("/rest/v1/research_pages?on_conflict=owner_id,url",key,"POST",[row],
                                "resolution=merge-duplicates,return=minimal")
                        except RuntimeError as row_error:
                            print("Research cursor row rejected; continuing safely: "+str(row_error)[:300])

def country_for(url, text):
    d=host(url)
    if d.endswith((".com.au",".au")) or re.search(r"\bAustralia|Sydney|Melbourne|Brisbane|Perth|Adelaide\b",text,re.I): return "Australia"
    if d.endswith((".co.uk",".uk")) or re.search(r"\bUnited Kingdom|\bUK\b|London|Manchester|Birmingham|Scotland|Wales\b",text,re.I): return "UK"
    if d.endswith(".ca") or re.search(r"\bCanada|Toronto|Vancouver|Montreal|Calgary\b",text,re.I): return "Canada"
    if d.endswith(".in") or re.search(r"\bIndia|Hyderabad|Bengaluru|Mumbai|Chennai|Delhi\b",text,re.I): return "India"
    if d.endswith(".us") or re.search(r"\bUnited States|\bUSA\b|\bU\.S\.|New York|California|Texas|Florida|Seattle|Chicago\b",text,re.I): return "USA"
    return "Other international"

def service_for(text):
    t=text.lower()
    if any(k in t for k in ("chatbot","ai assistant","voice assistant")): return "AI chatbot / voice assistant"
    if any(k in t for k in ("android app","mobile app","app developer")): return "Android / mobile app development"
    if any(k in t for k in ("excel","spreadsheet","data cleanup","data cleaning","powerpoint")): return "Excel / data / office services"
    if any(k in t for k in ("telugu","translation","localization","proofreading")): return "Telugu-English localization / QA"
    if any(k in t for k in ("seo","content writer","technical writer","blog article")): return "Content / SEO / technical writing"
    if any(k in t for k in ("logo","graphic designer","thumbnail","banner")): return "Graphic design / digital assets"
    if any(k in t for k in ("automation","workflow")): return "Business workflow automation"
    return "Website / web application development"


def main():
    os.makedirs("data",exist_ok=True)
    key,owner_id=owner_context()
    seen=load_seen_urls(key,owner_id)
    # Rotate through result pages each hour. Rechecking page 1 forever would
    # skip every URL already seen and never discover older/newly indexed buyers.
    page_offset=datetime.now(timezone.utc).hour % 10
    stats={"search_page_offset":page_offset,"queries":0,"search_results":0,"empty_searches":0,"pages_checked":0,"pages_skipped_seen":0,"page_failures":0,"qualified_pages":0,"potential_pages":0,"new_candidates":0}
    discovered=[]
    reddit_results=discover_reddit_requests()
    stats["reddit_buyer_posts_found"]=len(reddit_results)
    discovered.extend(reddit_results)
    social_results=discover_social_requests()
    stats["social_buyer_posts_found"]=len(social_results)
    discovered.extend(social_results)
    for query in QUERIES:
        stats["queries"]+=1
        results=search(query,page_offset)
        stats["search_results"]+=len(results)
        if not results: stats["empty_searches"]+=1
        discovered.extend(results)
    def region_rank(item):
        d=host(item[1])
        context=(item[0]+" "+item[2]).lower()
        if d.endswith((".com.au",".au",".co.uk",".uk",".us")) or any(x in context for x in ("united states","usa","u.s.","united kingdom","australia","sydney","london","new york","california","texas")): return 0
        if d.endswith(".ca") or "canada" in context: return 1
        if d.endswith(".in") or "india" in context: return 3
        return 2
    discovered.sort(key=region_rank)
    checked_urls=set()
    seen_records=[]
    candidates=[]
    # Inspect substantially more source pages each run; strict qualification still happens on-page.
    max_checks_per_run=300
    for title,url,snippet,provider in discovered:
        if stats["pages_checked"]>=max_checks_per_run or len(candidates)>=50: break
        domain=host(url)
        normalized=url.split("#")[0].rstrip("/")
        if not url.startswith("http") or "." not in domain or is_skipped(domain): continue
        path=urlparse(url).path or "/"
        combined=re.sub(r"\s+"," ",title+" "+snippet)
        # Do not reject a result from its short search snippet: snippets often contain generic words\n        # such as "jobs", "resources" or "portfolio" even when the original page is a paid project.\n        # Apply the stricter unpaid/job/low-quality checks only after fetching the source page.\n        if NON_BUYER_PATH.search(path): continue
        if normalized in checked_urls: continue
        checked_urls.add(normalized)
        if normalized in seen:
            stats["pages_skipped_seen"]+=1
            continue
        stats["pages_checked"]+=1
        reddit_verified=False
        contact_method=""
        if normalized in SOCIAL_PAGE_CACHE:
            page,reddit_verified,contact_method=SOCIAL_PAGE_CACHE[normalized]
        elif domain.endswith("reddit.com"):
            page,reddit_verified,contact_method=fetch_reddit_post(url)
        else:
            page=get(url,timeout=6)
        now=datetime.now(timezone.utc)
        outcome="page_fetch_failed"
        next_check=now+timedelta(days=1)
        evidence_excerpt=""
        if not page:
            stats["page_failures"]+=1
            if owner_id: seen_records.append({"owner_id":owner_id,"url":normalized,"domain":domain,"source_name":provider,"outcome":outcome,"evidence_excerpt":"","checked_at":now.isoformat(),"next_check_at":next_check.isoformat()})
            continue
        parser=Links()
        try: parser.feed(page)
        except Exception: pass
        page_text=re.sub(r"\s+"," "," ".join(parser.text))
        if not page_text:
            outcome="empty_page"
            next_check=now+timedelta(days=7)
            if owner_id: seen_records.append({"owner_id":owner_id,"url":normalized,"domain":domain,"source_name":provider,"outcome":outcome,"checked_at":now.isoformat(),"next_check_at":next_check.isoformat()})
            continue
        intent_probe=INTENT.search(page_text)
        paid_probe=PAID_SIGNAL.search(page_text)
        direct_probe=DIRECT_INTENT.search(page_text)
        # Social cache entries are buyer-authored posts/comments, not publisher pages.
        # The explicit first-person requirement matcher is sufficient to establish intent;
        # do not require a second website-style phrase match that drops genuine requests.
        if reddit_verified and intent_probe:
            direct_probe=True
        paid_request=bool(intent_probe and paid_probe and direct_probe
            and abs(intent_probe.start()-paid_probe.start())<=600
            and not UNPAID_SIGNAL.search(page_text[:12000])
            and not LOW_QUALITY.search(page_text[:12000])
            and not JOB_LISTING.search(page_text[:12000]))
        # Public buyer requests without a stated budget are retained as research prospects,
        # never mislabeled as paid-confirmed leads and never eligible for automatic outreach.
        potential_request=bool(intent_probe and direct_probe and not paid_probe
            and not UNPAID_SIGNAL.search(page_text[:12000])
            and not LOW_QUALITY.search(page_text[:12000])
            and not JOB_LISTING.search(page_text[:12000]))
        on_page_intent=paid_request or potential_request
        emails=set(EMAIL_RE.findall(page_text))
        phone=extract_public_phone(page_text,parser.links)
        phone_source=url if phone else ""
        contact_url=url if reddit_verified else ""
        contact_form_verified=False
        for href,label in parser.links:
            candidate=urljoin(url,href)
            if host(candidate)!=domain or "contact" not in (href+" "+label).lower(): continue
            contact_html=get(candidate,timeout=4)
            if not contact_html: continue
            contact_url=candidate
            contact_form_verified=bool(re.search(r"<form\b",contact_html,re.I))
            cp=Links()
            try: cp.feed(contact_html)
            except Exception: pass
            emails.update(EMAIL_RE.findall(" ".join(cp.text)))
            emails.update(re.findall(r"mailto:([^\"'<>? ]+)",contact_html,re.I))
            break
        emails={e.lower().strip(".,;:") for e in emails if EMAIL_RE.fullmatch(e.lower().strip(".,;:")) and not any(x in e.lower() for x in ["example.com","domain.com","wixpress.com","sentry.io","cloudflare.com","noreply","no-reply"])}
        email=sorted(emails)[0] if emails else ""
        evidence_excerpt=""
        contact_verified=bool(email or contact_form_verified or reddit_verified)
        if not on_page_intent:
            outcome="no_explicit_paid_business_request"
            next_check=now+timedelta(days=14)
        elif not contact_verified:
            outcome="contact_route_not_verified"
            next_check=now+timedelta(days=7)
        else:
            outcome="qualified_public_request" if paid_request else "potential_buyer_request"
            next_check=now+timedelta(days=90 if paid_request else 7)
            if paid_request: stats["qualified_pages"]+=1
            else: stats["potential_pages"]+=1
            intent_match=INTENT.search(page_text)
            paid_match=PAID_SIGNAL.search(page_text)
            evidence_excerpt=page_text[max(0,intent_match.start()-180):min(len(page_text),intent_match.end()+300)] if intent_match else page_text[:350]
            paid_excerpt=page_text[max(0,paid_match.start()-100):min(len(page_text),paid_match.end()+180)] if paid_match else ""
            page_title=re.search(r"<title[^>]*>(.*?)</title>",page,re.I|re.S)
            company=html.unescape(re.sub(r"<[^>]+>"," ",page_title.group(1))).strip() if page_title else title
            company=re.sub(r"\s+"," ",company).split(" | ")[0].split(" — ")[0][:180] or title[:180]
            evidence="Direct requirement: "+evidence_excerpt[:350]+(" | Paid signal: "+paid_excerpt[:180] if paid_request else " | Buyer budget/payment not stated; verify before quoting.")
            candidates.append({
                "company":company,"country":country_for(url,page_text),"contact":"","contact_url":contact_url or url,
                "email":email,"phone":phone,"phone_source":phone_source,"paidSignal":"Yes" if paid_request else "Unconfirmed","website":url,"source":url,"discovery_method":provider,
                "contactMethod": "Public email" if email else ("Public contact form" if contact_form_verified else "Public buyer-post thread"),
                "service":service_for(evidence_excerpt+" "+paid_excerpt),"status":"Qualified lead" if paid_request else "Potential lead",
                "evidence":evidence,
                "notes":"Buyer-authored request with a public reply path. Budget/payment is unconfirmed; owner must verify scope and payment before treating it as a paid project." if not paid_request else "Buyer-authored public paid-project request with a public contact route. Client acceptance is not guaranteed.",
                "needStage":"Client need confirmed" if paid_request else "Buyer request found — budget unconfirmed","contactVerified":"Yes","clientNeedConfirmed":"Yes",
                "needEvidenceUrl":url,"financialApproved":"No","discovered_at":now.isoformat(),
                "contactVerificationMethod": contact_method or ("Public email displayed on the source website" if email else "Public contact form verified on source website" if contact_form_verified else "Public buyer post with existing replies")
            })
        if owner_id: seen_records.append({"owner_id":owner_id,"url":normalized,"domain":domain,"source_name":provider,"outcome":outcome,"evidence_excerpt":evidence_excerpt[:500],"checked_at":now.isoformat(),"next_check_at":next_check.isoformat()})
    if key and owner_id:
        save_seen_pages(key,seen_records)
    cols=["company","country","contact","contact_url","email","contactMethod","paidSignal","website","source","discovery_method","service","status","evidence","notes","needStage","contactVerified","clientNeedConfirmed","needEvidenceUrl","financialApproved","discovered_at","contactVerificationMethod","phone","phone_source"]
    with open(OUT,"w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
        for row in candidates:w.writerow({k:row.get(k,"") for k in cols})
    stats["new_candidates"]=len(candidates)
    with open("data/research_stats.json","w",encoding="utf-8") as f:
        json.dump(stats,f,ensure_ascii=False)
    print("Diagnostics: "+", ".join(f"{k}={v}" for k,v in stats.items()))
    print(f"Saved {len(candidates)} verified paid-project buyer requests with a public email, contact form, or active reply path. Unverified pages remain excluded from the private lead pipeline.")

if __name__=="__main__": main()
