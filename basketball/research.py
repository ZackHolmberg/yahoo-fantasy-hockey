"""Collect public NBA evidence through Firecrawl; never infer draft eligibility."""
from datetime import datetime, timedelta, timezone
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4

from .config import path, write_json

API = "https://api.firecrawl.dev/v2/"


def public_nba_url(value):
    """Only public NBA content, with no account URLs, credentials or query strings."""
    url = urllib.parse.urlsplit(value)
    host = (url.hostname or "").lower()
    allowed = (host in {"nba.com", "www.nba.com"} and url.path.startswith(("/news/", "/player/", "/team/")) or
               host in {"espn.com", "www.espn.com"} and url.path.startswith("/nba/"))
    if url.scheme != "https" or not allowed or url.username or url.password or url.port or url.query or url.fragment:
        raise ValueError("Research requires a public NBA.com news/player/team or ESPN.com/nba URL without query parameters")
    return value


class Firecrawl:
    def post(self, endpoint, payload):
        headers = {"Content-Type": "application/json", "User-Agent": "basketball-research/1.0"}
        key = os.environ.get("FIRECRAWL_API_KEY")
        if key:
            headers["Authorization"] = "Bearer " + key
        request = urllib.request.Request(API + endpoint, data=json.dumps(payload).encode(), headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=55) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            # Provider bodies can echo request headers. Keep secrets out of diagnostics.
            raise ValueError(f"Firecrawl HTTP {exc.code}; check service limits or FIRECRAWL_API_KEY") from None
        if not isinstance(result, dict) or result.get("success") is not True or "data" not in result:
            raise ValueError("Firecrawl returned an unsuccessful or malformed response")
        return result["data"]

    def search(self, query, limit, tbs=None):
        payload = {"query": query, "limit": limit, "sources": ["web"],
                   "includeDomains": ["nba.com", "espn.com"]}
        if tbs:
            payload["tbs"] = tbs
        data = self.post("search", payload)
        if not isinstance(data, dict) or not isinstance(data.get("web"), list):
            raise ValueError("Firecrawl search response has no web-results list")
        return data["web"][:limit]

    def scrape(self, url):
        data = self.post("scrape", {"url": public_nba_url(url), "formats": ["markdown"],
                                    "onlyMainContent": True, "maxAge": 0})
        if not isinstance(data, dict) or not isinstance(data.get("markdown"), str) or not data["markdown"].strip():
            raise ValueError("Firecrawl returned no article content")
        metadata = data.get("metadata", {})
        if metadata.get("error") or metadata.get("statusCode", 200) != 200:
            raise ValueError("Firecrawl could not retrieve the article successfully")
        for field in ("sourceURL", "url"):
            if metadata.get(field):
                public_nba_url(metadata[field])
        return data


def collect(cfg, player, limit=3, days=30, url=None, client=None):
    player = player.strip()
    if not player or len(player) > 100 or any(ord(c) < 32 for c in player):
        raise ValueError("Supply one player name, at most 100 characters")
    if not 1 <= limit <= 5 or not 1 <= days <= 365:
        raise ValueError("Research limit must be 1-5 and days must be 1-365")
    if url:
        public_nba_url(url)
    client = client or Firecrawl()
    captured = datetime.now(timezone.utc)
    evidence = {"player": player, "retrieved_at": captured.isoformat(), "provider": "firecrawl",
                "review_status": "unreviewed", "eligibility": "unknown", "searches": [], "articles": [], "errors": []}
    candidates = [{"url": url}] if url else []
    if not url:
        quoted = '"' + player.replace('"', '') + '" NBA '
        end = captured.date()
        period = f"cdr:1,cd_min:{(end-timedelta(days=days)).strftime('%m/%d/%Y')},cd_max:{end.strftime('%m/%d/%Y')}"
        # Retirement can predate the recent injury window, so search it separately.
        for query, tbs in ((quoted + "team injury status", period), (quoted + "retirement retires", None)):
            results = client.search(query, limit, tbs)
            evidence["searches"].append({"query": query, "tbs": tbs, "results": results})
            candidates.extend(results)
    seen = set()
    for candidate in candidates:
        source = candidate.get("url", "")
        if source in seen:
            continue
        seen.add(source)
        try:
            public_nba_url(source)
            article = client.scrape(source)
            evidence["articles"].append({**article, "requested_url": source, "search_title": candidate.get("title"),
                                         "retrieved_at": datetime.now(timezone.utc).isoformat()})
        except (ValueError, OSError) as exc:
            evidence["errors"].append({"url": source, "error": str(exc)})
    evidence["complete"] = bool(evidence["articles"]) and not evidence["errors"]
    # Unique immutable captures preserve prior evidence and avoid concurrent overwrites.
    stem = captured.strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
    target = path(cfg, "research") / (stem + ".json")
    write_json(target, evidence)
    report = target.with_suffix(".md")
    lines = [f"# NBA research: {player}", "", f"Retrieved: {evidence['retrieved_at']}", "",
             "Review: unreviewed. Draft eligibility: unknown.", "",
             "Search results and article text require review of player identity, publication date and current relevance.",
             "Retrieval time is not publication time. No results does not establish that a player is active.",
             "This evidence does not change rankings or authorize picks.", ""]
    for article in evidence["articles"]:
        metadata = article.get("metadata", {})
        title = metadata.get("title") or article.get("search_title") or article["requested_url"]
        lines += [f"- [{title}]({article['requested_url']})", f"  Retrieved: {article['retrieved_at']}"]
    if evidence["errors"]:
        lines += ["", "Incomplete collection:"] + [f"- {e['url']}: {e['error']}" for e in evidence["errors"]]
    if not evidence["articles"]:
        lines += ["", "No usable articles were collected. Eligibility remains unknown."]
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"player": player, "articles": len(evidence["articles"]), "complete": evidence["complete"],
            "review_status": "unreviewed", "eligibility": "unknown", "evidence": str(target), "report": str(report)}
