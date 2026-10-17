"""ESPN FBA reads and checked transactions; credentials never enter snapshots or logs.

ESPN does not publish a stable API contract. Mappings are cross-checked against
https://github.com/cwendt94/espn-api/tree/master/espn_api/basketball .
"""
import json
import urllib.error
import urllib.request
from urllib.parse import urlencode

from .config import (SLOTS, STATS, credentials, identity, instant, now, path,
                     read_json, write_json)


class Client:
    def __init__(self, cfg):
        self.cfg = cfg
        self.base = f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{cfg['season']}"
        self.league = f"{self.base}/segments/0/leagues/{cfg['league_id']}"

    def request(self, url, body=None, filters=None, text=False):
        auth = credentials(self.cfg)
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json",
                   "X-Fantasy-Source": "kona", "X-Fantasy-Platform": "espn-fantasy-web"}
        if auth["espn_s2"]:
            headers["Cookie"] = f"espn_s2={auth['espn_s2']}; SWID={auth['SWID']}"
        if filters:
            headers["x-fantasy-filter"] = json.dumps(filters)
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                data = response.read().decode("utf-8")
                if text:
                    # ESPN's draftSecurity endpoint may return plain text or a
                    # JSON string. Neither form is persisted or logged.
                    return json.loads(data) if data.startswith('"') else data.strip()
                return json.loads(data)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise ValueError("ESPN authentication required. Run `python -m basketball login` or set ESPN_S2 and ESPN_SWID.") from exc
            # Do not include arbitrary response bodies: they can contain account data.
            raise ValueError(f"ESPN refused the request (HTTP {exc.code}); no local success was recorded.") from exc

    def settings(self):
        return self.request(self.league + "?view=mSettings&view=mStatus&view=mTeam&view=mDraftDetail")

    def draft_init(self):
        filters = {"players": {"filterStatsForContainerIds": {
            "value": [f"00{self.cfg['season'] - 1}", f"10{self.cfg['season']}"]}}}
        return self.request(self.league + "?" + urlencode({"view": ["draftInit", "mSettings"],
                                                           "filter": json.dumps(filters)}, doseq=True))

    def fetch(self):
        league = self.request(self.league + "?view=mSettings&view=mStatus&view=mTeam&view=mRoster&view=mMatchup&view=mDraftDetail&view=mPendingTransactions")
        if int(league.get("id", 0)) != self.cfg["league_id"]:
            raise ValueError("ESPN returned a different league")
        players, offset = [], 0
        while True:
            data = self.request(self.league + "?view=kona_player_info", filters={"players": {
                "limit": 500, "offset": offset, "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
                "filterStatsForExternalIds": {"value": [self.cfg["season"], self.cfg["season"] - 1, self.cfg["season"] - 2]},
                "filterStatsForSourceIds": {"value": [0, 1]}, "filterStatsForSplitTypeIds": {"value": [0]}}})
            page = data.get("players")
            if page is None:
                raise ValueError("ESPN player response is missing players")
            players += page
            if len(page) < 500 or len(players) >= data.get("totalPlayerCount", float("inf")):
                break
            offset += len(page)
            if offset >= 10000:
                raise ValueError("Player pagination did not finish; refusing a truncated pool")
        if len({p["player"]["id"] for p in players}) != len(players):
            raise ValueError("ESPN repeated a page; refusing a partial player pool")
        matchup = league.get("status", {}).get("currentMatchupPeriod")
        periods = league.get("settings", {}).get("scheduleSettings", {}).get("matchupPeriods", {}).get(str(matchup), [])
        periods = [int(p) for p in periods if int(p) <= (league.get("scoringPeriodId") or 0)]
        if periods:
            transactions = {}
            for period in periods:
                data = self.request(self.league + f"?view=mTransactions2&scoringPeriodId={period}", filters={"transactions": {
                    "filterType": {"value": ["FREEAGENT", "WAIVER", "TRADE_PROPOSAL", "TRADE_ACCEPT", "TRADE_DECLINE"]}}})
                if "transactions" not in data:
                    raise ValueError("ESPN transaction history is missing; cannot establish acquisition budget")
                page = data["transactions"]
                if data.get("totalTransactionCount", len(page)) > len(page):
                    raise ValueError("ESPN returned a partial transaction history; refusing to guess acquisition usage")
                transactions.update({t["id"]: t for t in page})
            league["basketballTransactions"] = list(transactions.values())
        season = self.request(self.base + "?view=proTeamSchedules_wl")
        snapshot = normalize(self.cfg, league, players, season)
        write_json(path(self.cfg, "snapshot.json"), snapshot)
        return snapshot

    def send(self, body):
        url = self.league.replace("lm-api-reads", "lm-api-writes") + "/transactions/"
        response = self.request(url, body)
        status = response.get("status") or next((t.get("status") for t in response.get("transactions", [])), None)
        if status not in {"EXECUTED", "PENDING"}:
            raise ValueError(f"ESPN did not confirm execution (status {status or 'unknown'}); refresh before retrying")
        return {"status": status, "id": response.get("id"),
                "transaction_ids": [t.get("id") for t in response.get("transactions", [])]}


def stats(record):
    return {STATS.get(int(k), str(k)): float(v) for k, v in record.items() if v is not None}


def player(entry, owner=None, slot=None):
    pool = entry.get("playerPoolEntry", entry)
    p = pool.get("player", pool)
    # draftInit supplies a year in externalId; kona_player_info uses seasonId.
    splits = [{"season": int(s.get("seasonId", s.get("externalId", 0))), "source": s.get("statSourceId", 0),
               "stats": stats(s.get("stats", {}))} for s in p.get("stats", [])
              if s.get("scoringPeriodId", 0) == 0 and s.get("statSplitTypeId", 0) == 0]
    eligible = [SLOTS[s] for s in p.get("eligibleSlots", []) if s in SLOTS]
    own = pool.get("onTeamId", owner or 0)
    return {"id": int(p["id"]), "name": p["fullName"], "team": str(p.get("proTeamId", 0)),
            "primary": SLOTS.get(p.get("defaultPositionId", 0) - 1, "?"), "eligible": eligible,
            "owner": int(own or 0), "slot": SLOTS.get(entry.get("lineupSlotId"), slot),
            "status": p.get("injuryStatus", "ACTIVE"), "undroppable": p.get("isUndroppable", False),
            "availability": pool.get("status", "ONTEAM" if own else "FREEAGENT"),
            "adp": (p.get("ownership") or {}).get("averageDraftPosition"),
            "auction_value": (p.get("ownership") or {}).get("auctionValueAverage"),
            "splits": splits}


def normalize(cfg, league, pool, season):
    if int(league.get("id", 0)) != cfg["league_id"] or league.get("seasonId", cfg["season"]) != cfg["season"] or league.get("gameId", 3) != 3:
        raise ValueError("ESPN export does not match the configured basketball league/season")
    if len({int(x["player"]["id"]) for x in pool}) != len(pool):
        raise ValueError("ESPN player pool contains duplicate IDs")
    by = {int(x["player"]["id"]): player(x) for x in pool}
    teams = []
    for t in league.get("teams", []):
        roster = []
        for entry in t.get("roster", {}).get("entries", []):
            p = player(entry, t["id"])
            if p["id"] in by and not p["splits"]:
                p["splits"] = by[p["id"]]["splits"]
            p["owner"] = t["id"]
            by[p["id"]] = p
            roster.append(p["id"])
        used = t.get("transactionCounter", {}).get("matchupAcquisitions")
        if "basketballTransactions" in league:
            period_ids = league.get("settings", {}).get("scheduleSettings", {}).get("matchupPeriods", {}).get(str(league.get("status", {}).get("currentMatchupPeriod")), [])
            used = sum(x.get("teamId") == t["id"] and x.get("scoringPeriodId") in period_ids
                       and x.get("status") in {"EXECUTED", "PENDING"}
                       and x.get("type") in {"FREEAGENT", "WAIVER"}
                       and any(i.get("type") == "ADD" for i in x.get("items", [])) for x in league["basketballTransactions"])
        teams.append({"id": t["id"], "name": t.get("name") or (t.get("location", "") + " " + t.get("nickname", "")).strip(),
                      "roster": roster, "record": t.get("record", {}),
                      "acquisitions": used, "season_acquisitions": t.get("transactionCounter", {}).get("acquisitions"),
                      "totals": stats(t["valuesByStat"]) if "valuesByStat" in t else None,
                      "acquisition_budget_spent": t.get("transactionCounter", {}).get("acquisitionBudgetSpent", 0)})
    if cfg["team_id"] not in {t["id"] for t in teams}:
        raise ValueError("Configured team is not in this league")
    games = {}
    tz = now(cfg).tzinfo
    for t in season.get("settings", {}).get("proTeams", []):
        seen, result = set(), []
        for period, rows in t.get("proGamesByScoringPeriod", {}).items():
            for g in rows:
                if g.get("id") in seen:
                    continue
                seen.add(g.get("id"))
                start = instant(g["date"])
                result.append({"id": g.get("id"), "date": start.astimezone(tz).date().isoformat(),
                               "start": start.isoformat(), "period": int(period),
                               "cancelled": g.get("status") in {"STATUS_CANCELED", "STATUS_POSTPONED"}})
        games[str(t["id"])] = sorted(result, key=lambda g: g["start"])
    status = league.get("status", {})
    matchups = league.get("schedule", [])
    return {**identity(cfg), "fetched_at": now(cfg).isoformat(), "source": "espn",
            "period": league.get("scoringPeriodId", status.get("latestScoringPeriod")),
            "transaction_period": status.get("transactionScoringPeriod", league.get("scoringPeriodId")),
            "matchup_period": status.get("currentMatchupPeriod"),
            "players": list(by.values()), "teams": teams, "games": games,
            "draft": league.get("draftDetail", {}), "draft_complete": league.get("draftDetail", {}).get("drafted"), "matchups": matchups,
            "settings": league.get("settings", {}),
            "pending": league.get("pendingTransactions", []) + [t for t in league.get("basketballTransactions", []) if t.get("status") == "PENDING"],
            "transactions": league.get("basketballTransactions", [])}


def load_snapshot(cfg, filename=None, fresh=False):
    snapshot = Client(cfg).fetch() if fresh else read_json(filename or path(cfg, "snapshot.json"))
    if not snapshot:
        raise ValueError("No snapshot. Run `python -m basketball fetch` or supply --snapshot FILE.")
    if any(snapshot.get(k) != v for k, v in identity(cfg).items()):
        raise ValueError("Snapshot belongs to a different league, team or season")
    if len({p["id"] for p in snapshot["players"]}) != len(snapshot["players"]):
        raise ValueError("Snapshot has duplicate player IDs")
    return snapshot


def import_settings(cfg, raw, persist=True):
    """Import authoritative rules without replacing local owner policy."""
    settings = raw["settings"]
    scoring = settings["scoringSettings"]
    kind = scoring.get("scoringType", "")
    formats = {"H2H_POINTS": "points", "H2H_CATEGORY": "categories", "H2H_CATEGORIES": "categories",
               "H2H_MOST_CATEGORIES": "categories", "ROTO": "roto", "TOTAL_POINTS": "points"}
    if kind not in formats:
        raise ValueError(f"Unknown ESPN scoring format {kind!r}; inspect settings before configuring")
    cfg["format"] = formats[kind]
    cfg["scoring"] = {STATS[int(s["statId"])]: s["points"] for s in scoring["scoringItems"] if int(s["statId"]) in STATS}
    cfg["categories"] = [STATS[int(s["statId"])] for s in scoring["scoringItems"] if int(s["statId"]) in STATS]
    cfg["slots"] = {SLOTS[int(k)]: v for k, v in settings["rosterSettings"]["lineupSlotCounts"].items() if v and int(k) in SLOTS}
    if any(int(k) not in SLOTS and v for k, v in settings["rosterSettings"]["lineupSlotCounts"].items()):
        raise ValueError("ESPN returned unsupported roster slots")
    cfg["teams"] = settings.get("size", len(raw.get("teams", [])))
    cfg["name"] = settings.get("name", cfg.get("name"))
    roster = settings["rosterSettings"]
    lock = roster.get("lineupLocktimeType")
    if lock in {"INDIVIDUAL_GAME", "SCORING_PERIOD"}:
        cfg["lineup_lock"] = "daily" if lock == "INDIVIDUAL_GAME" else "weekly"
    elif lock is not None:
        raise ValueError(f"Unknown lineup lock {lock!r}; inspect ESPN settings")
    if "positionLimits" in roster:
        cfg["position_limits"] = {SLOTS[int(k) - 1]: v for k, v in roster["positionLimits"].items() if int(k) in range(1, 6) and v >= 0}
    acq = settings.get("acquisitionSettings", {})
    if "matchupAcquisitionLimit" in acq:
        cfg["acquisition_limit"] = acq["matchupAcquisitionLimit"] if acq["matchupAcquisitionLimit"] >= 0 else None
    if "acquisitionLimit" in acq:
        cfg["season_acquisition_limit"] = acq["acquisitionLimit"] if acq["acquisitionLimit"] >= 0 else None
    if "waiverHours" in acq:
        cfg["waiver_days"] = acq["waiverHours"] / 24
    if "acquisitionBudget" in acq:
        cfg["faab_budget"] = acq["acquisitionBudget"]
    if "minimumBid" in acq:
        cfg["faab_minimum_bid"] = acq["minimumBid"]
    types = {"WAIVERS_TRADITIONAL": "rolling", "WAIVERS_CONTINUOUS": "faab", "FREE_AGENT": "free_agent"}
    if acq.get("acquisitionType") in types:
        cfg["waiver_system"] = types[acq["acquisitionType"]]
    draft = settings.get("draftSettings", {})
    if draft.get("type") in {"SNAKE", "AUCTION"}:
        cfg["draft"]["type"] = draft["type"].lower()
    if draft.get("date"):
        cfg["draft"]["date"] = instant(draft["date"]).astimezone(now(cfg).tzinfo).isoformat()
    if "timePerSelection" in draft:
        cfg["draft"]["seconds_per_pick"] = draft["timePerSelection"]
    if draft.get("auctionBudget"):
        cfg["draft"]["budget"] = draft["auctionBudget"]
    order = draft.get("pickOrder", [])
    if cfg["team_id"] in order:
        cfg["draft"]["slot"] = order.index(cfg["team_id"]) + 1
    deadline = settings.get("tradeSettings", {}).get("deadlineDate")
    if deadline:
        cfg["trade_deadline"] = instant(deadline).isoformat()
    cfg["lower_is_better"] = [STATS[int(s["statId"])] for s in scoring["scoringItems"]
                              if s.get("isReverseItem") and int(s["statId"]) in STATS] or cfg.get("lower_is_better", ["TO"])
    cfg["verified_at"] = now(cfg).date().isoformat()
    # Keep the raw schema for audit. Games-cap schemas vary across formats;
    # explicit games_caps/games_used remain required rather than guessing.
    if persist:
        write_json(path(cfg, "settings.json"), raw)
        write_json(cfg["_path"], {k: v for k, v in cfg.items() if not k.startswith("_")})
    return cfg


def login(cfg):
    """Interactive login; only ESPN cookies are persisted, never browser history."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ValueError("Install basketball dependencies and Chromium; see docs/BASKETBALL.md") from exc
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(f"https://fantasy.espn.com/basketball/team?leagueId={cfg['league_id']}&teamId={cfg['team_id']}&seasonId={cfg['season']}")
        input("Sign in to ESPN in the opened browser, then press Enter here: ")
        cookies = {c["name"]: c["value"] for c in context.cookies() if c["name"] in {"espn_s2", "SWID"}
                   and (c["domain"].lstrip(".") == "espn.com" or c["domain"].endswith(".espn.com"))}
        if not cookies.get("espn_s2") or not cookies.get("SWID"):
            raise ValueError("ESPN login cookies were not found; nothing was saved")
        write_json(path(cfg, "auth.json"), cookies)
        browser.close()
    Client(cfg).settings()
    return {"authenticated": True, **identity(cfg)}
