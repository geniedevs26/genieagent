const ALLOWED_SUBREDDITS = new Set([
  "forhire",
  "FreelanceIndia",
  "DoneDirtCheap",
  "WordpressJobs",
  "DesignJobs",
  "AndroidJobs",
]);

export async function onRequestGet({ request }) {
  const url = new URL(request.url);
  const subreddit = url.searchParams.get("sub") || "";
  if (!ALLOWED_SUBREDDITS.has(subreddit)) {
    return new Response("Unsupported subreddit", {
      status: 400,
      headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" },
    });
  }

  const upstreamUrl = `https://www.reddit.com/r/${subreddit}/new/.rss?limit=100`;
  try {
    const upstream = await fetch(upstreamUrl, {
      headers: {
        "Accept": "application/atom+xml, application/xml;q=0.9, text/xml;q=0.8",
        "User-Agent": "Mozilla/5.0 (compatible; GenieAgentLeadResearch/1.0; +https://genieagent.pages.dev/)",
      },
      redirect: "follow",
    });
    if (!upstream.ok) {
      return new Response(`Reddit feed unavailable (HTTP ${upstream.status})`, {
        status: 502,
        headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" },
      });
    }
    const xml = await upstream.text();
    if (!xml.includes("<feed") || xml.length > 5_000_000) {
      return new Response("Invalid or oversized feed response", {
        status: 502,
        headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" },
      });
    }
    return new Response(xml, {
      status: 200,
      headers: {
        "Content-Type": "application/atom+xml; charset=utf-8",
        "Cache-Control": "public, max-age=120, s-maxage=120",
        "X-Content-Type-Options": "nosniff",
        "Access-Control-Allow-Origin": "*",
      },
    });
  } catch {
    return new Response("Reddit feed request failed", {
      status: 502,
      headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" },
    });
  }
}
