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

  const rssUrl = `https://www.reddit.com/r/${subreddit}/new/.rss?limit=20`;
  const converterUrl = `https://api.rss2json.com/v1/api.json?rss_url=${encodeURIComponent(rssUrl)}`;
  try {
    const upstream = await fetch(converterUrl, {
      headers: { "Accept": "application/json" },
      redirect: "follow",
    });
    if (!upstream.ok) {
      return new Response(`Public feed converter unavailable (HTTP ${upstream.status})`, {
        status: 502,
        headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" },
      });
    }
    const data = await upstream.json();
    if (data?.status !== "ok" || !Array.isArray(data.items)) {
      return new Response("Public feed conversion failed", {
        status: 502,
        headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" },
      });
    }
    const safe = {
      status: "ok",
      feed: { title: String(data.feed?.title || `r/${subreddit}`), url: rssUrl },
      items: data.items.slice(0, 10).map((item) => ({
        title: String(item.title || "").slice(0, 500),
        link: String(item.link || "").slice(0, 2000),
        pubDate: String(item.pubDate || "").slice(0, 80),
        author: String(item.author || "").slice(0, 160),
        content: String(item.content || item.description || "").slice(0, 30000),
      })),
    };
    return new Response(JSON.stringify(safe), {
      status: 200,
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "public, max-age=120, s-maxage=120",
        "X-Content-Type-Options": "nosniff",
        "Access-Control-Allow-Origin": "*",
      },
    });
  } catch {
    return new Response("Public feed request failed", {
      status: 502,
      headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" },
    });
  }
}
