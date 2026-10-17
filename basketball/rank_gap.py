"""Retrospective expert-minus-ESPN rank experiments with per-pick audit trails."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import random
import statistics

from .backtest import digest, get_json, input_model, totals_for
from .config import active_slots, load, read_json, roster_size, write_json
from .planner import assign, legal_roster
from .strategy_lab import grade, key, legal

POLICIES = ("expert_best", "gap_all", "gap_window")
YEARS = (2023, 2024, 2025, 2026)


def valid_rank(value):
    return type(value) is int and 0 < value < 999


def api_ranks(rows):
    result = {}
    seen = set()
    for row in rows:
        player = row.get("player", row)
        pid = int(player["id"])
        if pid in seen:
            raise ValueError("Duplicate ESPN player identity")
        seen.add(pid)
        rank = player.get("draftRanksByRankType", {}).get("STANDARD", {}).get("rank")
        if valid_rank(rank):
            result[pid] = rank
    if not result:
        raise ValueError("No valid STANDARD draft ranks")
    return result


def file_hash(file):
    return hashlib.sha256(Path(file).read_bytes()).hexdigest()


def sources():
    names = ("rank_gap.py", "strategy_lab.py", "backtest.py", "model.py", "planner.py", "config.py")
    return {name: hashlib.sha256(Path(__file__).with_name(name).read_text(encoding="utf-8").encode()).hexdigest()
            for name in names}


def prepare(root, lab_root):
    scenarios = []
    for year in YEARS:
        pack = read_json(lab_root / f"input-{year}.json")
        if not pack or pack["season"] != year:
            raise ValueError("Missing/mismatched historical input")
        url = f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{year}/players?view=kona_player_info"
        rawfile = root / "raw" / f"draft-ranks-{year}.json"
        rows = get_json(url, rawfile, {"x-fantasy-filter": json.dumps({"limit": 2000, "offset": 0,
                                "sortDraftRanks": {"sortPriority": 1, "sortAsc": True, "value": "STANDARD"}})})
        for mode in (("api", "published") if year == 2025 else ("api",)):
            expert_field = "independent_rank" if year == 2025 else "expert_rank"
            expert = {p["id"]: p[expert_field] for p in pack["players"] if valid_rank(p.get(expert_field))}
            market = api_ranks(rows) if mode == "api" else {
                p["id"]: p["expert_rank"] for p in pack["players"] if valid_rank(p.get("expert_rank"))}
            ids = {p["id"] for p in pack["players"]}
            entry = {"id": f"{year}-{mode}", "season": year, "mode": mode, "pack": pack,
                     "expert": expert, "market": {pid: rank for pid, rank in market.items() if pid in ids},
                     "expert_source": "Rotoworld points PDF" if year == 2025 else "ESPN points PDF",
                     "market_source": {"url": url, "sha256": file_hash(rawfile), "preseason_timestamp_verified": False}
                     if mode == "api" else {"source": pack["sources"][0], "preseason_timestamp_verified": True},
                     "coverage": {"expert": len(expert), "market_in_pool": len(ids & market.keys()),
                                  "both": len(expert.keys() & market.keys()), "market_outside_pool": len(market.keys()-ids)}}
            scenarios.append(entry)
    write_json(root / "inputs.json", scenarios)
    return [{k: s[k] for k in ("id", "expert_source", "coverage")} for s in scenarios]


def ranking(model, scenario):
    expert = {int(pid): rank for pid, rank in scenario["expert"].items()}
    market = {int(pid): rank for pid, rank in scenario["market"].items()}
    year = model.cfg["season"]
    latest = {p["id"]: next((s["stats"] for s in p["splits"] if s["season"] == year-1), {}) for p in model.players}
    prior = sorted(model.by_id, key=lambda pid: (-sum(latest[pid].get(k, 0)*v for k, v in model.cfg["scoring"].items()), pid))
    pool = [pid for pid in prior if latest[pid].get("GP", 0) > 0 or pid in expert or pid in market]
    prior_order = {pid: i for i, pid in enumerate(prior)}
    def order(board):
        return sorted(pool, key=lambda pid: (pid not in board, board.get(pid, prior_order[pid]), pid))
    return expert, market, order(expert), order(market)


def choose(model, roster, gone, policy, expert, market, order):
    # Availability and roster legality are applied before looking at disagreement.
    available = [pid for pid in order if pid not in gone]
    best = next((pid for pid in available if legal(model, roster, pid)), None)
    if best is None:
        raise ValueError("No legal draft choice")
    bargains = [pid for pid in available if pid in expert and pid in market and expert[pid] < market[pid]]
    bargains.sort(key=lambda pid: (expert[pid]-market[pid], expert[pid], pid))
    # Only the first five legal bargains enter the audit; lower ones cannot win.
    shortlist = []
    for pid in bargains:
        if legal(model, roster, pid):
            shortlist.append(pid)
            if len(shortlist) == 5:
                break
    candidates = bargains
    if policy == "gap_window":
        candidates = [pid for pid in bargains if best in expert and expert[pid] < expert[best]+model.cfg["teams"]]
    elif policy not in POLICIES:
        raise ValueError("Unknown rank-gap policy")
    candidate = next((pid for pid in candidates if legal(model, roster, pid)), None) if policy != "expert_best" else None
    chosen = candidate if candidate is not None else best
    def row(pid):
        e, m = expert.get(pid), market.get(pid)
        return {"id": pid, "name": model.by_id[pid]["name"], "expert_rank": e, "espn_rank": m,
                "gap": e-m if e is not None and m is not None else None}
    return chosen, {**row(chosen), "best_expert_available": row(best),
                    "best_gaps_available": [row(pid) for pid in shortlist],
                    "fallback": policy != "expert_best" and candidate is None}


def simulate(model, target, policy, expert, market, expert_order, opponents):
    count = model.cfg["teams"]
    rosters = {team: [] for team in range(1, count+1)}
    gone, trace = set(), []
    for rnd in range(roster_size(model.cfg)):
        sequence = range(1, count+1) if rnd % 2 == 0 else range(count, 0, -1)
        for team in sequence:
            if team == target:
                pid, detail = choose(model, rosters[team], gone, policy, expert, market, expert_order)
                trace.append({"round": rnd+1, "pick": len(gone)+1, **detail})
            else:
                pid = next((pid for pid in opponents[team] if pid not in gone and legal(model, rosters[team], pid)), None)
                if pid is None:
                    raise ValueError("Opponent cannot complete legal roster")
            gone.add(pid)
            rosters[team].append(model.by_id[pid])
    for roster in rosters.values():
        if not legal_roster(roster, model.cfg) or len(assign(roster, active_slots(model.cfg))) != len(active_slots(model.cfg)):
            raise ValueError("Invalid completed roster")
    if len(gone) != count*roster_size(model.cfg):
        raise ValueError("Duplicate or incomplete draft")
    return {str(team): [p["id"] for p in roster] for team, roster in rosters.items()}, trace


def draft(root, cfg):
    if cfg["format"] != "points":
        raise ValueError("Rank-gap experiment requires points scoring")
    scenarios = read_json(root / "inputs.json")
    evidence = {"inputs_sha256": digest(scenarios), "source_sha256": sources(),
                "config": {k: cfg[k] for k in ("teams", "slots", "position_limits", "scoring", "format")}, "cases": []}
    for scenario in scenarios:
        model = input_model(cfg, scenario["pack"])
        expert, market, expert_order, market_order = ranking(model, scenario)
        ordinal = {pid: i+1 for i, pid in enumerate(market_order)}
        for seed in (-1, 0, 1):
            opponents = {}
            for team in range(1, cfg["teams"]+1):
                rng = random.Random(f"rank-gap:{scenario['id']}:{seed}:{team}")
                noise = {pid: rng.gauss(0, 12) if seed >= 0 else 0 for pid in market_order}
                opponents[team] = sorted(market_order, key=lambda pid: (ordinal[pid]+noise[pid], pid))
            for slot in range(1, cfg["teams"]+1):
                for policy in POLICIES:
                    rosters, trace = simulate(model, slot, policy, expert, market, expert_order, opponents)
                    evidence["cases"].append({"scenario": scenario["id"], "season": scenario["season"],
                                              "seed": seed, "slot": slot, "policy": policy, "rosters": rosters, "trace": trace})
            print(json.dumps({"scenario": scenario["id"], "seed": seed, "drafts": len(evidence["cases"])}), flush=True)
    write_json(root / "decisions.json", evidence)
    (root / "decisions.sha256").write_text(digest(evidence)+"\n")
    return {"drafts": len(evidence["cases"]), "decision_sha256": digest(evidence)}


def locked(root):
    evidence = read_json(root / "decisions.json")
    scenarios = read_json(root / "inputs.json")
    if (digest(evidence) != (root / "decisions.sha256").read_text().strip() or
            evidence["inputs_sha256"] != digest(scenarios) or evidence["source_sha256"] != sources()):
        raise ValueError("Locked decisions, inputs or source changed")
    return evidence, scenarios


def score(root, cfg, history_root):
    evidence, scenarios = locked(root)
    cfg = copy.deepcopy(cfg)
    cfg.update(evidence["config"])
    models = {s["id"]: input_model(cfg, s["pack"]) for s in scenarios}
    outcomes = {year: totals_for(year, history_root) for year in YEARS}
    rows = []
    for case in evidence["cases"]:
        roster = case["rosters"][str(case["slot"])]
        rows.append({**{k: case[k] for k in ("scenario", "season", "seed", "slot", "policy")},
                     **grade(models[case["scenario"]], roster, outcomes[case["season"]])})
    baseline = {(r["scenario"], r["seed"], r["slot"]): r for r in rows if r["policy"] == "expert_best"}
    for r in rows:
        b = baseline[(r["scenario"], r["seed"], r["slot"])]
        r.update(gain_pct=100*(r["starting_nine"]/b["starting_nine"]-1),
                 roster_gain_pct=100*(r["total"]/b["total"]-1), win=r["starting_nine"] > b["starting_nine"])
    summary = []
    for scenario in scenarios:
        for policy in POLICIES:
            group = [r for r in rows if r["scenario"] == scenario["id"] and r["policy"] == policy]
            gains = sorted(r["gain_pct"] for r in group)
            summary.append({"scenario": scenario["id"], "policy": policy, "drafts": len(group),
                            **{k: round(statistics.mean(r[k] for r in group), 4) for k in
                               ("total", "starting_nine", "gain_pct", "roster_gain_pct", "zero_games", "win")},
                            "gain_p10": round(gains[int(.1*len(gains))], 4), "gain_p90": round(gains[int(.9*len(gains))], 4)})
    result = {"decision_sha256": digest(evidence), "source_sha256": evidence["source_sha256"],
              "inputs_sha256": evidence["inputs_sha256"], "config": evidence["config"],
              "scenarios": [{k: s[k] for k in ("id", "season", "expert_source", "market_source", "coverage")} for s in scenarios],
              "summary": summary, "rows": rows}
    write_json(root / "results.json", result)
    return {k: v for k, v in result.items() if k != "rows"}


def current(root, init_file, expert_file):
    init, board = read_json(init_file), read_json(expert_file)
    if init["seasonId"] != board["season"]:
        raise ValueError("Current boards have different seasons")
    market = api_ranks(init["players"])
    names = {}
    for row in init["players"]:
        p = row["player"]
        normalized = key(p["fullName"])
        if normalized in names:
            raise ValueError("Ambiguous current player name")
        names[normalized] = int(p["id"])
    rows = []
    for rank, player in board["ranks"].items():
        pid = names.get(key(player["name"]))
        espn = market.get(pid)
        rows.append({"id": pid, "name": player["name"], "expert_rank": int(rank), "espn_rank": espn,
                     "gap": int(rank)-espn if espn else None, "availability_checked": False})
    result = {"season": board["season"], "expert_source": board["source"], "expert_sha256": board["sha256"],
              "draft_init_sha256": file_hash(init_file), "draft_init_file_modified_at": init_file.stat().st_mtime,
              "snapshot_warning": "Cached draft-room snapshot; refresh for live decisions. Availability unchecked.",
              "rows": sorted(rows, key=lambda r: (r["gap"] is None, r["gap"] or 0, r["expert_rank"]))}
    write_json(root / "current-board.json", result)
    return {"season": board["season"], "matched": sum(r["gap"] is not None for r in rows), "unmatched": [r["name"] for r in rows if r["gap"] is None]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "draft", "score", "current"))
    parser.add_argument("--root", type=Path, default=Path("basketball/data/rank-gap"))
    parser.add_argument("--lab-root", type=Path, default=Path("basketball/data/strategy-lab"))
    parser.add_argument("--history-root", type=Path, default=Path("basketball/data/backtest"))
    parser.add_argument("--draft-init", type=Path, default=Path("basketball/data/api-practice/runtime/draft-init.json"))
    parser.add_argument("--expert-board", type=Path, default=Path("basketball/data/strategy-lab/current-source-comparison.json"))
    parser.add_argument("--config")
    args = parser.parse_args()
    if args.action == "prepare":
        result = prepare(args.root, args.lab_root)
    elif args.action == "current":
        result = current(args.root, args.draft_init, args.expert_board)
    elif args.action == "draft":
        result = draft(args.root, load(args.config))
    else:
        result = score(args.root, load(args.config), args.history_root)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
