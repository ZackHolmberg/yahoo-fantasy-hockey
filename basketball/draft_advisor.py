"""Explicitly selected, read-only current-season expert / market advisor."""
from collections import defaultdict

from . import availability, bans, drafting
from .config import path, read_json, roster_size
from .hybrid import Hybrid
from .ranking_library import checked_board
from .strategy_lab import key, legal


def orders(model, source, library):
    if source not in {"rotowire", "rotoworld", "fantrax", "consensus"}:
        raise ValueError("Unknown expert source")
    market = sorted((p["id"] for p in model.players if type(p.get("draft_rank")) is int and 0 < p["draft_rank"] < 999),
                    key=lambda p: (model.by_id[p]["draft_rank"], p))
    if not market:
        raise ValueError("Snapshot has no ESPN STANDARD draft ranks; refresh/import a current player pool first")
    identities = defaultdict(list)
    for pid in market:
        identities[key(model.by_id[pid]["name"])].append(pid)
    needed = ("rotowire", "rotoworld", "fantrax") if source == "consensus" else (source,)
    published, details, completed = {}, [], {"espn": market}
    m = {pid: i for i, pid in enumerate(market)}
    for name in needed:
        file = library / "boards" / f"{name}-{model.cfg['season']}.json"
        board = read_json(file)
        if not board:
            raise ValueError(f"Missing collected current expert board: {file}")
        checked_board(library, board)
        if (board["source"]["season"] != model.cfg["season"] or board["source"]["format"] != "points"
                or board["status"] not in {"prospective", "preseason"}):
            raise ValueError("Advisor requires a verified current-season preseason points board")
        ranks, unresolved = {}, []
        for row in board["rows"]:
            matches = identities.get(key(row["name"]), [])
            if len(matches) != 1:
                unresolved.append(row["name"])
            else:
                ranks[matches[0]] = row["rank"]
        if not ranks:
            raise ValueError("No expert players matched the ESPN market pool")
        published[name] = ranks
        completed[name] = sorted(market, key=lambda p: (p not in ranks, ranks.get(p, m[p]), m[p], p))
        details.append({"source": name, "family": board["source"]["family"], "url": board["source"]["url"],
                        "published_rows": len(board["rows"]), "matched_rows": len(ranks), "unresolved_or_no_market_rank": unresolved,
                        "retrieved_at": board["retrieved_at"], "board_sha256": board["board_sha256"]})
    if source == "consensus":
        ordinal = [{pid: i for i, pid in enumerate(order)} for order in completed.values()]
        quality = sorted(market, key=lambda p: (sum(r[p] for r in ordinal), m[p], p))
    else:
        quality = completed[source]
    return quality, market, published, details


def legal_choices(model, order):
    """Draft legality is independent of whether ESPN supplied a projection."""
    picks = drafting.state(model)["picks"]
    if any(p["player"] not in model.by_id for p in picks):
        raise ValueError("Drafted players are missing from the snapshot; refresh the pool")
    gone = {p["player"] for p in picks}
    mine = [model.by_id[p["player"]] for p in picks if p["team"] == model.cfg["team_id"]]
    policy = bans.listing(model.cfg)
    return [pid for pid in order if pid not in gone and model.by_id[pid]["owner"] in (0, model.cfg["team_id"])
            and model.by_id[pid].get("active") is not False
            and not bans.reason(model.cfg, model.by_id[pid], policy=policy) and legal(model, mine, pid)]


def expert_board(model, source="rotowire", limit=20):
    """Greedy expert order, with ESPN completion only for unpublished tails."""
    if model.cfg["format"] != "points" or model.cfg["draft"]["type"] != "snake":
        raise ValueError("Expert drafting requires a points snake draft")
    quality, _, published, details = orders(model, source, path(model.cfg, "ranking-library"))
    ordinal = {pid: i+1 for i, pid in enumerate(quality)}
    choices = legal_choices(model, quality)[:limit]
    return {"strategy": "expert", "source": source, "sources": details, "availability_checked": False,
            "players": [{"id": pid, "name": model.by_id[pid]["name"], "quality_order": ordinal[pid],
                         "espn_rank": model.by_id[pid]["draft_rank"],
                         "published_expert_ranks": {name: ranks.get(pid) for name, ranks in published.items()}}
                        for pid in choices]}


def board(model, source="consensus", slot=None, current=None, library=None, verify=False):
    cfg = model.cfg
    if cfg["format"] != "points" or cfg["draft"]["type"] != "snake":
        raise ValueError("Hybrid advisor requires a points snake draft")
    order = model.snapshot.get("settings", {}).get("draftSettings", {}).get("pickOrder", [])
    inferred = order.index(cfg["team_id"])+1 if cfg["team_id"] in order else None
    slot = slot or inferred or cfg["draft"].get("slot")
    if type(slot) is not int or not 1 <= slot <= cfg["teams"]:
        raise ValueError("Supply your known snake slot with --slot")
    picks = drafting.state(model)["picks"]
    if sorted(p["pick"] for p in picks) != list(range(1, len(picks)+1)) or len({p["player"] for p in picks}) != len(picks):
        raise ValueError("Draft history must contain unique, consecutive completed picks")
    if any(p["player"] not in model.by_id for p in picks):
        raise ValueError("Drafted players are missing from the snapshot; refresh the pool")
    turn = len(picks)+1
    if current is not None and current != turn:
        raise ValueError("Requested pick disagrees with tracked draft history; sync picks first")
    turns = drafting.snake_picks(cfg["teams"], slot, roster_size(cfg))
    if turn not in turns:
        raise ValueError("Hybrid advice requires our current snake turn; sync picks and confirm slot")
    mine = [p["player"] for p in picks if p["team"] == cfg["team_id"]]
    if len(mine) != turns.index(turn):
        raise ValueError("Tracked team selections disagree with this snake slot")
    quality, market, published, details = orders(model, source, library or path(cfg, "ranking-library"))
    chooser = Hybrid(quality, market)
    gone = {p["player"] for p in picks} | {p["id"] for p in model.players if p["owner"] not in (0, cfg["team_id"])}
    policy = bans.listing(cfg)
    excluded = {p["id"] for p in model.players if p.get("active") is False or bans.reason(cfg, p, policy=policy)}
    following = next((p for p in turns if p > turn), None)
    gap = following-turn-1 if following else 0

    def allowed(roster, pid):
        return legal(model, [model.by_id[p] for p in roster], pid)

    checks = []
    while True:
        choice = chooser.choose(gone, mine, gap, allowed, final=following is None, excluded=excluded)
        if not verify:
            break
        status = availability.check(cfg, model.by_id[choice["id"]])
        checks.append(status)
        if status["allowed"]:
            break
        excluded.add(choice["id"])
        if len(checks) >= 20:
            raise ValueError("No verified hybrid recommendation among twenty candidates; inspect availability checks")

    def describe(pid):
        p = model.by_id[pid]
        return {"id": pid, "name": p["name"], "quality_order": chooser.rank[pid], "espn_rank": p["draft_rank"],
                "published_expert_ranks": {name: ranks.get(pid) for name, ranks in published.items()}}

    return {"advisory_only": True, "strategy": source+"_hybrid", "pick": turn, "next_pick": following,
            "recommendation": describe(choice["id"]), "best_expert": describe(choice["best_expert"]),
            "deferred": choice["deferred"], "reason": choice["reason"], "intervening_picks": gap,
            "alternatives": [{**r, **describe(r["id"])} for r in choice["alternatives"]], "sources": details,
            "snapshot_at": model.snapshot["fetched_at"], "market_pool": len(market), "ban_list": policy,
            "availability_checked": verify, "availability_checks": checks,
            "note": "Two-pick rank utility and scenario counts are heuristics, not expected points or probabilities. Unpublished tails follow ESPN. Default auto-drafting is unchanged."}
