"""Fixed ranking-source comparisons: prepare, lock drafts, then score outcomes."""
import argparse
import copy
from datetime import datetime
import hashlib
from pathlib import Path
import random
import statistics

from .backtest import digest, input_model, totals_for
from .config import active_slots, load, read_json, roster_size, write_json
from .planner import assign, legal_roster
from .ranking_library import checked_board
from .strategy_lab import grade, legal

YEARS = (2018, 2019, 2023, 2024, 2025, 2026)


def source_hashes():
    return {name: hashlib.sha256(Path(__file__).with_name(name).read_text(encoding="utf-8").encode()).hexdigest()
            for name in ("source_backtest.py", "ranking_library.py", "strategy_lab.py", "backtest.py", "model.py", "planner.py", "config.py")}


def prepare(root, library, inventory_file):
    inventory = read_json(inventory_file)
    expected = {p["season"]: p["input_sha256"] for p in inventory["historical_inputs"]}
    packs = []
    for year in YEARS:
        pack = read_json(library / f"input-{year}.json")
        if digest(pack) != expected[year]:
            raise ValueError("Historical input differs from the committed source inventory")
        for source in pack["sources"]:
            board = read_json(library / "boards" / (source["id"]+".json"))
            checked_board(library, board)
            if board["status"] != "preseason" or board["source"]["format"] != "points" or board["sha256"] != source["sha256"]:
                raise ValueError("Historical source is not an accepted preseason points board")
        packs.append(pack)
    inputs = {"inventory_sha256": digest(inventory), "packs": packs}
    write_json(root / "inputs.json", inputs)
    return {"seasons": YEARS, "inputs_sha256": digest(inputs)}


def primary_sources(pack):
    selected = {}
    for source in pack["sources"]:
        date = source["date_evidence"].get("datePublished") or source["date_evidence"]["CreationDate"]
        stamp = datetime.fromisoformat(date.replace("Z", "+00:00"))
        score = (source["basis"] != "projected points per game", stamp, source["id"])
        family = source["family"]
        if family not in selected or score > selected[family][0]:
            selected[family] = score, source["id"]
    return {family: value[1] for family, value in selected.items()}


def preferences(model, pack):
    boards = {source: {int(pid): rank for pid, rank in ranks.items()} for source, ranks in pack["ranking_boards"].items()}
    year = pack["season"]
    latest = {p["id"]: next((s["stats"] for s in p["splits"] if s["season"] == year-1), {}) for p in model.players}
    published = set().union(*(set(board) for board in boards.values()))
    pool = [pid for pid in model.by_id if latest[pid].get("GP", 0) > 0 or pid in published]
    prior = sorted(pool, key=lambda pid: (-sum(latest[pid].get(k, 0)*w for k, w in model.cfg["scoring"].items()), pid))
    prior_rank = {pid: i for i, pid in enumerate(prior)}
    baseline = boards[pack["baseline_source"]]
    espn = sorted(pool, key=lambda pid: (pid not in baseline, baseline.get(pid, prior_rank[pid]), pid))
    espn_rank = {pid: i for i, pid in enumerate(espn)}
    completed = {source: sorted(pool, key=lambda pid: (pid not in ranks, ranks.get(pid, espn_rank[pid]), espn_rank[pid], pid))
                 for source, ranks in boards.items()}
    policies = {"espn": {"order": espn, "sources": [pack["baseline_source"]]},
                "prior_total": {"order": prior, "sources": []}}
    for source in boards:
        if source != pack["baseline_source"]:
            policies["source:"+source] = {"order": completed[source], "sources": [source]}
    primary = primary_sources(pack)
    if len(primary) > 1:
        ordinal = {source: {pid: i for i, pid in enumerate(completed[source])} for source in primary.values()}
        consensus = sorted(pool, key=lambda pid: (sum(order[pid] for order in ordinal.values()), espn_rank[pid], pid))
        policies["publisher_consensus"] = {"order": consensus, "sources": sorted(primary.values())}
    for policy in policies.values():
        policy["coverage"] = set.intersection(*(set(boards[source]) for source in policy["sources"])) if policy["sources"] else set()
    return policies, boards, primary


def simulate(model, target, policy, opponents, published, espn):
    count = model.cfg["teams"]
    rosters = {team: [] for team in range(1, count+1)}
    gone, trace = set(), []
    for rnd in range(roster_size(model.cfg)):
        sequence = range(1, count+1) if rnd % 2 == 0 else range(count, 0, -1)
        for team in sequence:
            order = policy["order"] if team == target else opponents[team]
            pid = next((pid for pid in order if pid not in gone and legal(model, rosters[team], pid)), None)
            if pid is None:
                raise ValueError("No legal remaining draft choice")
            if team == target:
                trace.append({"round": rnd+1, "pick": len(gone)+1, "id": pid, "name": model.by_id[pid]["name"],
                              "source_ranks": {source: published[source].get(pid) for source in policy["sources"]},
                              "espn_rank": espn.get(pid), "source_covered": pid in policy["coverage"]})
            gone.add(pid)
            rosters[team].append(model.by_id[pid])
    for roster in rosters.values():
        if not legal_roster(roster, model.cfg) or len(assign(roster, active_slots(model.cfg))) != len(active_slots(model.cfg)):
            raise ValueError("Invalid completed roster")
    if len(gone) != count*roster_size(model.cfg):
        raise ValueError("Duplicate or incomplete draft")
    return {str(t): [p["id"] for p in roster] for t, roster in rosters.items()}, trace


def draft(root, cfg):
    if cfg["format"] != "points":
        raise ValueError("Source comparison requires points scoring")
    inputs = read_json(root / "inputs.json")
    evidence = {"inputs_sha256": digest(inputs), "source_sha256": source_hashes(), "cases": [], "policy_sources": {},
                "primary_sources": {}, "config": {k: cfg[k] for k in ("teams", "slots", "position_limits", "scoring", "format")}}
    for pack in inputs["packs"]:
        model, year = input_model(cfg, pack), pack["season"]
        policies, published, primary = preferences(model, pack)
        evidence["policy_sources"][str(year)] = {p: data["sources"] for p, data in policies.items()}
        evidence["primary_sources"][str(year)] = primary
        fields = {"espn": policies["espn"]["order"]}
        if "publisher_consensus" in policies and policies["publisher_consensus"]["order"] != fields["espn"]:
            fields["consensus"] = policies["publisher_consensus"]["order"]
        for field, order in fields.items():
            ordinal = {pid: i for i, pid in enumerate(order)}
            for seed in (-1, 0, 1):
                opponents = {}
                for team in range(1, cfg["teams"]+1):
                    rng = random.Random(f"source-comparison:{year}:{field}:{seed}:{team}")
                    noise = {pid: rng.gauss(0, 12) if seed >= 0 else 0 for pid in order}
                    opponents[team] = sorted(order, key=lambda pid: (ordinal[pid]+noise[pid], pid))
                for slot in range(1, cfg["teams"]+1):
                    for policy, data in policies.items():
                        rosters, trace = simulate(model, slot, data, opponents, published, published[pack["baseline_source"]])
                        evidence["cases"].append({"season": year, "field": field, "seed": seed, "slot": slot,
                                                  "policy": policy, "rosters": rosters, "trace": trace})
                print(f"Drafted {year} {field} seed {seed}: {len(evidence['cases'])} complete leagues", flush=True)
    write_json(root / "decisions.json", evidence)
    (root / "decisions.sha256").write_text(digest(evidence)+"\n")
    return {"drafts": len(evidence["cases"]), "decision_sha256": digest(evidence)}


def locked(root):
    evidence = read_json(root / "decisions.json")
    inputs = read_json(root / "inputs.json")
    if (digest(evidence) != (root / "decisions.sha256").read_text().strip() or evidence["inputs_sha256"] != digest(inputs)
            or evidence["source_sha256"] != source_hashes()):
        raise ValueError("Locked inputs, implementation or decisions changed")
    return evidence, inputs


def summarize(rows):
    gains = sorted(r["gain_pct"] for r in rows)
    return {"drafts": len(rows), **{k: round(statistics.mean(r[k] for r in rows), 5) for k in
            ("total", "starting_nine", "gain_pct", "roster_gain_pct", "win", "zero_games", "low_games", "covered_pick_share")},
            "gain_p10": round(gains[int(.1*len(gains))], 5), "gain_p90": round(gains[int(.9*len(gains))], 5)}


def score(root, cfg, history_root):
    evidence, inputs = locked(root)
    cfg = copy.deepcopy(cfg)
    cfg.update(evidence["config"])
    models = {p["season"]: input_model(cfg, p) for p in inputs["packs"]}
    outcomes = {year: totals_for(year, history_root) for year in models}
    rows, cache = [], {}
    for case in evidence["cases"]:
        roster = case["rosters"][str(case["slot"])]
        identity = case["season"], tuple(sorted(roster))
        if identity not in cache:
            cache[identity] = grade(models[case["season"]], roster, outcomes[case["season"]])
        rows.append({**{k: case[k] for k in ("season", "field", "seed", "slot", "policy")}, **cache[identity],
                     "covered_pick_share": sum(p["source_covered"] for p in case["trace"])/len(roster)})
    baseline = {(r["season"], r["field"], r["seed"], r["slot"]): r for r in rows if r["policy"] == "espn"}
    for row in rows:
        base = baseline[(row["season"], row["field"], row["seed"], row["slot"])]
        row.update(gain_pct=100*(row["starting_nine"]/base["starting_nine"]-1),
                   roster_gain_pct=100*(row["total"]/base["total"]-1), win=row["starting_nine"] > base["starting_nine"])
    summary = []
    for year, field, policy in sorted({(r["season"], r["field"], r["policy"]) for r in rows}):
        summary.append({"season": year, "field": field, "policy": policy,
                        **summarize([r for r in rows if (r["season"], r["field"], r["policy"]) == (year, field, policy)])})
    aggregates = []
    for group in ("espn", "prior_total", "publisher_consensus", "rotowire_primary"):
        selected = [r for r in rows if r["policy"] == group or group == "rotowire_primary" and
                    r["policy"] == "source:"+evidence["primary_sources"][str(r["season"])].get("RotoWire", "")]
        seasons = sorted({r["season"] for r in selected})
        per_season = [summarize([r for r in selected if r["season"] == year]) for year in seasons]
        if per_season:
            aggregates.append({"policy": group, "seasons": seasons, "drafts": len(selected),
                               **{k: round(statistics.mean(s[k] for s in per_season), 5) for k in
                                  ("gain_pct", "roster_gain_pct", "win", "zero_games", "low_games", "covered_pick_share")}})
    result = {"decision_sha256": digest(evidence), "inputs_sha256": evidence["inputs_sha256"],
              "source_sha256": evidence["source_sha256"], "config": evidence["config"], "primary_sources": evidence["primary_sources"],
              "policy_sources": evidence["policy_sources"], "summary": summary, "aggregate": aggregates, "rows": rows}
    write_json(root / "results.json", result)
    return {k: v for k, v in result.items() if k != "rows"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "draft", "score"))
    parser.add_argument("--root", type=Path, default=Path("basketball/data/source-backtest"))
    parser.add_argument("--library", type=Path, default=Path("basketball/data/ranking-library"))
    parser.add_argument("--inventory", type=Path, default=Path("docs/basketball_data_inventory.json"))
    parser.add_argument("--history-root", type=Path, default=Path("basketball/data/backtest"))
    parser.add_argument("--config")
    args = parser.parse_args()
    if args.action == "prepare":
        result = prepare(args.root, args.library, args.inventory)
    elif args.action == "draft":
        result = draft(args.root, load(args.config))
    else:
        result = score(args.root, load(args.config), args.history_root)
    print(result)


if __name__ == "__main__":
    main()
