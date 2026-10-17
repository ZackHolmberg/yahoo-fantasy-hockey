"""Current public ESPN evidence required before any draft write.

This gate does not change projections, rank values, or historical experiments.
"""
from datetime import timedelta
import hashlib
import json
import re
import urllib.request

from .config import instant, now, path, read_json, write_json
from . import bans

SITE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/"
PROFILE = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/"
MAX_AGE = 900


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def fresh(value, at):
    try:
        return -60 <= (at - instant(value)).total_seconds() <= MAX_AGE
    except (ValueError, TypeError, OverflowError):
        return False


class Sources:
    def __init__(self, cfg):
        self.cfg = cfg

    def get(self, url, refresh=False):
        filename = path(self.cfg, "availability-cache") / (hashlib.sha256(url.encode()).hexdigest()+".json")
        saved = read_json(filename)
        if not refresh and saved and saved.get("url") == url and fresh(saved.get("fetched_at"), now(self.cfg)):
            return saved["data"]
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(request, timeout=6) as response:
            data = json.load(response)
        if not isinstance(data, dict):
            raise ValueError("Public availability response is malformed")
        write_json(filename, {"url": url, "fetched_at": now(self.cfg).isoformat(), "data": data})
        return data


def athlete_id(athlete):
    ids = {int(athlete["id"])} if athlete.get("id") else set()
    for link in athlete.get("links", []):
        match = re.match(r"^https://www\.espn\.com/nba/player(?:/[^/]+)?/_/id/(\d+)(?:/|$)", link.get("href", ""))
        if match:
            ids.add(int(match[1]))
    if len(ids) != 1:
        raise ValueError("Injury report cannot identify exactly one ESPN athlete ID")
    return ids.pop()


def injury_record(row):
    details = row.get("details") or {}
    return {"status": row.get("status"), "designation": (details.get("fantasyStatus") or {}).get("abbreviation"),
            "return_date": details.get("returnDate"), "published_at": row.get("date"),
            "description": row.get("shortComment", "")}


def check(cfg, player, refresh=False, sources=None):
    at = now(cfg)
    result = {"id": player["id"], "name": player.get("name", str(player["id"])), "season": cfg["season"],
              "checked_at": at.isoformat(), "expires_at": (at+timedelta(seconds=MAX_AGE)).isoformat(),
              "status": "unknown", "allowed": False, "reasons": [], "sources": [], "injuries": [],
              "fantasy_state": {k: player.get(k) for k in ("status", "active", "team")}}
    sources = sources or Sources(cfg)
    try:
        bans.require(cfg, player)
        url = PROFILE + str(player["id"])
        raw = sources.get(url, refresh)
        result["sources"].append(url)
        profile = raw.get("athlete", {})
        if int(profile.get("id", 0)) != player["id"] or raw.get("season", {}).get("year") != cfg["season"]:
            raise ValueError("Public profile identity/season does not match")
        result["name"] = profile.get("displayName", result["name"])
        status = (profile.get("status") or {}).get("type", "").lower()
        if profile.get("active") is False or status in {"retired", "inactive", "deceased"} or player.get("active") is False:
            result.update(status="blocked", reasons=["Player is inactive in a current ESPN source"])
        elif profile.get("active") is not True or status != "active":
            raise ValueError("Current public profile does not confirm active NBA status")
        else:
            team = str((profile.get("team") or {}).get("id", ""))
            if not team.isdigit() or int(team) <= 0:
                raise ValueError("Current NBA team is not confirmed")
            url = SITE + f"teams/{team}/roster"
            roster = sources.get(url, refresh)
            result["sources"].append(url)
            if (roster.get("season", {}).get("year") != cfg["season"] or str(roster.get("team", {}).get("id")) != team or
                    not fresh(roster.get("timestamp"), at) or not isinstance(roster.get("athletes"), list)):
                raise ValueError("Current team roster identity/season/freshness is unverified")
            matches = [p for p in roster["athletes"] if int(p["id"]) == player["id"]]
            if len(matches) != 1:
                raise ValueError("Player is not uniquely present on the current NBA roster")
            member = matches[0]
            if (member.get("status") or {}).get("type", "").lower() != "active" or not isinstance(member.get("injuries"), list):
                raise ValueError("Current roster does not confirm active status/injury coverage")
            url = SITE + "injuries"
            report = sources.get(url, refresh)
            result["sources"].append(url)
            if report.get("status") != "success" or report.get("season", {}).get("year") != cfg["season"] or not fresh(report.get("timestamp"), at) or not isinstance(report.get("injuries"), list):
                raise ValueError("Current injury report season/freshness/coverage is unverified")
            injuries = list(member["injuries"])
            # The public profile legitimately omits this field for healthy players;
            # current roster injury coverage and the separate report are required.
            if "injuries" in profile and not isinstance(profile["injuries"], list):
                raise ValueError("Public profile injury data is malformed")
            injuries += profile.get("injuries", [])
            for group in report["injuries"]:
                if not isinstance(group.get("injuries"), list):
                    raise ValueError("Injury report contains an incomplete team record")
                for row in group["injuries"]:
                    if athlete_id(row.get("athlete", {})) == player["id"]:
                        injuries.append(row)
            records = {fingerprint(injury_record(row)): injury_record(row) for row in injuries}
            result["injuries"] = sorted(records.values(), key=fingerprint)
            result["team"] = team
            result["source_as_of"] = {"roster": roster["timestamp"], "injuries": report["timestamp"]}
            if any(r["designation"] == "OFS" for r in result["injuries"]):
                result.update(status="blocked", reasons=["Current structured injury report lists out-for-season"])
            elif result["injuries"] or player.get("status", "UNKNOWN") not in {"ACTIVE"}:
                result.update(status="review", reasons=["Current injury or conflicting fantasy status requires risk review"])
            elif str(player.get("team", team)) not in {team, "0"}:
                result.update(status="review", reasons=["Fantasy and current public NBA teams disagree"])
            else:
                result.update(status="clear", allowed=True, reasons=["Active public profile, current roster membership and no listed injury concern"])
        blocked = bans.reason(cfg, player, result.get("team"))
        if blocked:
            result.update(status="blocked", allowed=False, reasons=[blocked])
        result["condition_sha256"] = fingerprint({k: result.get(k) for k in ("id", "season", "status", "team", "injuries", "reasons", "fantasy_state")})
        review = read_json(path(cfg, "availability-reviews.json"), {}).get(str(player["id"]))
        if result["status"] == "review" and review and review.get("season") == cfg["season"] and review.get("condition_sha256") == result["condition_sha256"] and instant(review["expires_at"]) > at:
            result.update(status="risk_accepted", allowed=True, risk_review=review)
    except bans.BannedPlayer as exc:
        result.update(status="blocked", allowed=False, reasons=[str(exc)])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result.update(status="unknown", allowed=False, reasons=[str(exc)])
    filename = path(cfg, "availability-checks.json")
    saved = read_json(filename, {})
    saved[str(player["id"])] = result
    write_json(filename, saved)
    return result


def require(cfg, player):
    bans.require(cfg, player)
    result = check(cfg, player, refresh=True)
    if not result["allowed"]:
        raise ValueError(f"Availability {result['status']} for {result['name']}: {'; '.join(result['reasons'])}. Use draft availability/review-risk.")
    bans.require(cfg, player, result.get("team"))
    return result


def review_risk(cfg, player, note, hours):
    if not note.strip() or not 0 < hours <= 24:
        raise ValueError("Risk review needs a reason and an expiry of at most 24 hours")
    result = check(cfg, player, refresh=True)
    if result["status"] not in {"review", "risk_accepted"}:
        raise ValueError("Only verified reviewable concerns can be accepted; blocked/unknown players cannot be overridden")
    review = {"season": cfg["season"], "at": now(cfg).isoformat(), "expires_at": (now(cfg)+timedelta(hours=hours)).isoformat(),
              "condition_sha256": result["condition_sha256"], "reason": note.strip(), "sources": result["sources"]}
    filename = path(cfg, "availability-reviews.json")
    saved = read_json(filename, {})
    saved[str(player["id"])] = review
    write_json(filename, saved)
    return review


def verified_choice(model, candidates=None):
    from .bans import board
    checks = []
    for candidate in board(model)["players"] if candidates is None else candidates:
        result = check(model.cfg, model.by_id[candidate["id"]])
        checks.append(result)
        if result["allowed"]:
            return candidate, checks
    raise ValueError("No verified available candidate among the top 20 legal recommendations; inspect draft availability")
