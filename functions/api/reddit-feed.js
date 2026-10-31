const FEEDS = {
  "forhire-web": ["forhire", "title:Hiring web developer"],
  "forhire-website": ["forhire", "title:Hiring website"],
  "forhire-chatbot": ["forhire", "title:Hiring chatbot"],
  "forhire-automation": ["forhire", "title:Hiring automation"],
  "forhire-excel": ["forhire", "title:Hiring Excel"],
  "freelanceindia-web": ["FreelanceIndia", "title:Hiring website developer"],
  "freelanceindia-chatbot": ["FreelanceIndia", "title:Hiring chatbot"],
  "done-dirt-cheap-web": ["DoneDirtCheap", "title:Hiring website"],
  "wordpress-jobs": ["WordpressJobs", "title:Hiring WordPress"],
  "design-jobs-web": ["DesignJobs", "title:Hiring website design"],
  "android-jobs-app": ["AndroidJobs", "title:Hiring Android app"],
};

export async function onRequestGet({ request }) {
  const url = new URL(request.url);
  const feedKey = url.searchParams.get("feed") || "";
  const feed = FEEDS[feedKey];
  if (!feed) {
    return new Response("Unsupported feed", {
      status: 400,
      headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" },
    });
  }

  const [subreddit, query] = feed;
  const redditUrl = `https://www.reddit.com/r/${subreddit}/search.rss?q=${encodeURIComponent(query)}&restrict_sr=1&sort=new&t=month`;
  const upstreamUrl = `https://proxy.cors.dev/${redditUrl}`;
  try {
    const upstream = await fetch(upstreamUrl, {
      headers: { "Accept": "application/atom+xml, application/xml;q=0.9, text/xml;q=0.8" },
      redirect: "follow",
    });
    if (!upstream.ok) {
      return new Response(`Public Reddit feed unavailable (HTTP ${upstream.status})`, {
        status: 502,
        headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" },
      });
    }
    const xml = await upstream.text();
    if (!xml.includes("<feed") || xml.length > 5_000_000) {
      return new Response("Invalid or oversized Reddit feed response", {
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
    return new Response("Public Reddit feed request failed", {
      status: 502,
      headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" },
    });
  }
}
