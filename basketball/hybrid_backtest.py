"""Lock a paired hybrid timing experiment before scoring target outcomes."""
import argparse
import copy
from functools import lru_cache
import hashlib
from pathlib import Path
import random
import statistics

from .backtest import digest, input_model, totals_for
from .config import active_slots, load, read_json, roster_size, write_json
from .hybrid import Hybrid
from .planner import assign, legal_roster
from .source_backtest import locked as source_locked, preferences
from .strategy_lab import grade, legal

YEARS = (2023, 2025, 2026)
PROTOCOL = Path(__file__).resolve().parent.parent / "docs/BASKETBALL_HYBRID_PROTOCOL.md"


def hashes():
    names = ("hybrid.py", "hybrid_backtest.py")
    result = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in names}
    result[PROTOCOL.name] = hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()
    return result


def simulate(model, target, chooser, opponents, allowed):
    count = model.cfg["teams"]
    rosters = {team: [] for team in range(1, count+1)}
    gone, trace = set(), []
    for rnd in range(roster_size(model.cfg)):
        sequence = range(1, count+1) if rnd % 2 == 0 else range(count, 0, -1)
        for team in sequence:
            roster = rosters[team]
            if team == target:
                gap = 2*(count-target) if rnd % 2 == 0 else 2*(target-1)
                choice = chooser.choose(gone, roster, gap, allowed, final=rnd == roster_size(model.cfg)-1)
                pid = choice["id"]
                trace.append({**choice, "round": rnd+1, "pick": len(gone)+1, "name": model.by_id[pid]["name"]})
            else:
                pid = next((p for p in opponents[team] if p not in gone and allowed(tuple(roster), p)), None)
                if pid is None:
                    raise ValueError("No legal opponent choice")
            gone.add(pid)
            roster.append(pid)
    for roster in rosters.values():
        players = [model.by_id[p] for p in roster]
        if not legal_roster(players, model.cfg) or len(assign(players, active_slots(model.cfg))) != len(active_slots(model.cfg)):
            raise ValueError("Invalid completed roster")
    if len(gone) != count*roster_size(model.cfg):
        raise ValueError("Duplicate or incomplete league")
    return {str(t): r for t, r in rosters.items()}, trace


def draft(root, cfg, baseline):
    previous, inputs = source_locked(baseline)
    if {k: cfg[k] for k in previous["config"]} != previous["config"]:
        raise ValueError("Use the original league configuration for paired comparisons")
    packs = [p for p in inputs["packs"] if p["season"] in YEARS]
    if {p["season"] for p in packs} != set(YEARS):
        raise ValueError("Missing independent-source seasons")
    cases = []
    evidence = {"baseline_sha256": digest(previous), "inputs_sha256": digest(inputs), "source_sha256": hashes(),
                "config": previous["config"], "cases": cases}
    for pack in packs:
        model, year = input_model(cfg, pack), pack["season"]
        policies, _, primary = preferences(model, pack)
        names = ("source:"+primary["RotoWire"], "publisher_consensus")
        selected = {"rotowire": policies[names[0]], "consensus": policies[names[1]]}
        mapping = {"espn": "espn", names[0]: "rotowire", names[1]: "consensus"}
        for case in previous["cases"]:
            if case["season"] == year and case["policy"] in mapping:
                cases.append({**case, "policy": mapping[case["policy"]]})

        @lru_cache(maxsize=200000)
        def cached(roster, pid):
            return legal(model, [model.by_id[p] for p in roster], pid)

        def allowed(roster, pid):
            return cached(tuple(sorted(roster)), pid)

        market = policies["espn"]["order"]
        choosers = {name: Hybrid(data["order"], market) for name, data in selected.items()}
        for field, order in (("espn", market), ("consensus", policies["publisher_consensus"]["order"])):
            ordinal = {p: i for i, p in enumerate(order)}
            for seed in (-1, 0, 1):
                opponents = {}
                for team in range(1, cfg["teams"]+1):
                    rng = random.Random(f"source-comparison:{year}:{field}:{seed}:{team}")
                    noise = {p: rng.gauss(0, 12) if seed >= 0 else 0 for p in order}
                    opponents[team] = sorted(order, key=lambda p: (ordinal[p]+noise[p], p))
                for slot in range(1, cfg["teams"]+1):
                    for name, chooser in choosers.items():
                        rosters, trace = simulate(model, slot, chooser, opponents, allowed)
                        cases.append({"season": year, "field": field, "seed": seed, "slot": slot,
                                      "policy": name+"_hybrid", "rosters": rosters, "trace": trace})
                print(f"Hybrid decisions: {year} {field} seed {seed}; {len(cases)} paired cases", flush=True)
        cached.cache_clear()
    write_json(root / "decisions.json", evidence)
    (root / "decisions.sha256").write_text(digest(evidence)+"\n")
    return {"cases": len(cases), "new_drafts": sum(c["policy"].endswith("_hybrid") for c in cases), "decision_sha256": digest(evidence)}


def locked(root, baseline):
    previous, inputs = source_locked(baseline)
    evidence = read_json(root / "decisions.json")
    if (digest(evidence) != (root / "decisions.sha256").read_text().strip() or evidence["source_sha256"] != hashes()
            or evidence["baseline_sha256"] != digest(previous) or evidence["inputs_sha256"] != digest(inputs)):
        raise ValueError("Hybrid inputs, baseline, code or decisions changed")
    return evidence, inputs


def summarize(rows):
    return {"drafts": len(rows), **{k: round(statistics.mean(r[k] for r in rows), 5) for k in
            ("gain_vs_espn", "gain_vs_expert", "roster_vs_espn", "roster_vs_expert", "win_vs_expert", "zero_games", "low_games", "deferred_share")}}


def score(root, cfg, baseline, history_root):
    evidence, inputs = locked(root, baseline)
    cfg = copy.deepcopy(cfg)
    cfg.update(evidence["config"])
    models = {p["season"]: input_model(cfg, p) for p in inputs["packs"] if p["season"] in YEARS}
    outcomes = {y: totals_for(y, history_root) for y in models}
    rows, cache = [], {}
    for case in evidence["cases"]:
        roster = case["rosters"][str(case["slot"])]
        identity = case["season"], tuple(sorted(roster))
        if identity not in cache:
            cache[identity] = grade(models[case["season"]], roster, outcomes[case["season"]])
        rows.append({**{k: case[k] for k in ("season", "field", "seed", "slot", "policy")}, **cache[identity],
                     "deferred_share": sum(p.get("deferred", False) for p in case["trace"])/len(roster)})
    paired = {(r["season"], r["field"], r["seed"], r["slot"], r["policy"]): r for r in rows}
    for row in rows:
        key = row["season"], row["field"], row["seed"], row["slot"]
        expert = row["policy"].removesuffix("_hybrid")
        for label, policy in (("espn", "espn"), ("expert", expert)):
            base = paired[(*key, policy)]
            row["gain_vs_"+label] = 100*(row["starting_nine"]/base["starting_nine"]-1)
            row["roster_vs_"+label] = 100*(row["total"]/base["total"]-1)
        row["win_vs_expert"] = row["starting_nine"] > paired[(*key, expert)]["starting_nine"]
    summaries = [{"season": y, "field": f, "policy": p, **summarize([r for r in rows if (r["season"], r["field"], r["policy"]) == (y, f, p)])}
                 for y, f, p in sorted({(r["season"], r["field"], r["policy"]) for r in rows})]
    aggregate = []
    for policy in sorted({r["policy"] for r in rows}):
        annual = [summarize([r for r in rows if r["season"] == y and r["policy"] == policy]) for y in YEARS]
        aggregate.append({"policy": policy, "drafts": sum(r["drafts"] for r in annual),
                          **{k: round(statistics.mean(r[k] for r in annual), 5) for k in annual[0] if k != "drafts"}})
    result = {"decision_sha256": digest(evidence), "aggregate": aggregate, "summary": summaries, "rows": rows}
    write_json(root / "results.json", result)
    return {k: v for k, v in result.items() if k != "rows"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("draft", "score"))
    parser.add_argument("--root", type=Path, default=Path("basketball/data/hybrid-backtest"))
    parser.add_argument("--baseline", type=Path, default=Path("basketball/data/source-backtest"))
    parser.add_argument("--history-root", type=Path, default=Path("basketball/data/backtest"))
    parser.add_argument("--config")
    args = parser.parse_args()
    if args.action == "draft":
        print(draft(args.root, load(args.config), args.baseline))
    else:
        print(score(args.root, load(args.config), args.baseline, args.history_root))


if __name__ == "__main__":
    main()
