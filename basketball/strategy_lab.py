"""Enriched historical draft experiments. Separate prepare, draft, develop, test phases."""
import argparse
import copy
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import random
import re
import statistics
import urllib.request

from .backtest import ARCHIVES, digest, get_json, input_model, name_key, totals_for
from .config import SLOTS, active_slots, load, read_json, roster_size, write_json
from .planner import assign, legal_roster

SHEETS = {**ARCHIVES,
          2024: "https://g.espncdn.com/s/fbadraftkit/2023-2024/FBA2024top200PTS.pdf",
          2026: "https://g.espncdn.com/s/fbadraftkit/2025-26/fbacheatsheetPts.pdf"}
NBC = "https://nbcsports.brightspotcdn.com/03/10/b09f526442aab7ad4db7ba3584ed/rotoworld-2024-25-fantasy-basketball-kit.pdf"
CUTOFF = {2023: "2022-10-17", 2024: "2023-10-23", 2025: "2024-10-21", 2026: "2025-10-21"}
STRATEGIES = ("prior_total", "history_blend", "recent_gate", "per_game", "durability", "expert_rank",
              "rank_blend", "risk_blend", "roster_fit", "market_patience")
DEVELOP = (2023, 2024, 2025)
TEST = 2026
TEAM_NAMES = ("Atlanta Hawks", "Boston Celtics", "Brooklyn Nets", "Charlotte Hornets", "Chicago Bulls",
              "Cleveland Cavaliers", "Dallas Mavericks", "Denver Nuggets", "Detroit Pistons", "Golden State Warriors",
              "Houston Rockets", "Indiana Pacers", "LA Clippers", "Los Angeles Clippers", "Los Angeles Lakers",
              "Memphis Grizzlies", "Miami Heat", "Milwaukee Bucks", "Minnesota Timberwolves", "New Orleans Pelicans",
              "New York Knicks", "Oklahoma City Thunder", "Orlando Magic", "Philadelphia 76ers", "Phoenix Suns",
              "Portland Trail Blazers", "Sacramento Kings", "San Antonio Spurs", "Toronto Raptors", "Utah Jazz", "Washington Wizards")


def profile_name(line):
    header = re.match(r"^\d+\s+(.+?)\s*(?:" + "|".join(re.escape(t) for t in TEAM_NAMES) + r")\b",
                      line.replace("G olden", "Golden"))
    return key(header[1]) if header else None


def key(name):
    value = name_key(name)
    value = re.sub(r"(?:jr|iii|ii)$", "", value)
    return {"shaedonsharp": "shaedonsharpe", "kenyonmartin": "kjmartin", "nicolaclaxton": "nicclaxton",
            "alexsarr": "alexandresarr", "robertdillingham": "robdillingham", "carltoncarrington": "bubcarrington",
            "ronholland": "ronaldholland"}.get(value, value)


def pdf_source(url, file, cutoff):
    import pdfplumber
    if not file.exists():
        file.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=45) as response:
            file.write_bytes(response.read())
    pdf = pdfplumber.open(file)
    dates = [str(pdf.metadata.get(k, ""))[2:10] for k in ("CreationDate", "ModDate")]
    if not all(re.fullmatch(r"\d{8}", d) and d < cutoff.replace("-", "") for d in dates):
        pdf.close()
        raise ValueError("PDF date missing or not before draft cutoff")
    provenance = {"url": url, "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
                  "pdf_dates": dates, "retrieved_at": datetime.now().astimezone().isoformat()}
    return pdf, provenance


def espn_ranks(text, expected):
    rows = {}
    for line in text.splitlines():
        matches = list(re.finditer(r"(?:^|\s)(\d+)\.\s+([^,\n]+),\s*", line))
        for i, match in enumerate(matches):
            tail = line[match.end():matches[i+1].start() if i+1 < len(matches) else len(line)]
            positions = list(dict.fromkeys(re.findall(r"\b(PG|SG|SF|PF|C)(?=\b|\d)", tail)))
            rank = int(match[1])
            if rank in rows or not positions:
                raise ValueError("Duplicate/incomplete preseason rank")
            rows[rank] = {"name": match[2].strip(), "positions": positions}
    if set(rows) != set(range(1, expected+1)):
        raise ValueError("Preseason sheet does not contain every expected rank")
    return rows


def nbc_data(pdf):
    # Separate columns before matching player headers and their PROJ row.
    projections, ranks, current = {}, {}, None
    for page in pdf.pages[4:71]:
        for left, right in ((0, page.width/2), (page.width/2, page.width)):
            text = page.crop((left, 0, right, page.height)).extract_text() or ""
            for line in text.splitlines():
                header = profile_name(line)
                if header:
                    current = header
                if line.startswith("PROJ "):
                    parts = line.split()
                    if not current or len(parts) < 18 or current in projections:
                        raise ValueError(f"Unmatched/duplicate numeric projection row: page {page.page_number}, {current}, {line}")
                    nums = [float(v.rstrip("%")) for v in parts[2:18]]
                    gp, minute, pts, fgm, fga, fg, ftm, fta, ft, three, reb, ast, stl, blk, to, yahoo = nums
                    if not 0 <= gp <= 82 or not 0 <= minute <= 48 or fgm > fga or ftm > fta or not all(math.isfinite(n) and n >= 0 for n in nums):
                        raise ValueError("Invalid preseason numeric projection")
                    projections[current] = {"GP": gp, "PTS": pts, "FGM": fgm, "FGA": fga, "FTM": ftm,
                                            "FTA": fta, "3PM": three, "REB": reb, "AST": ast, "STL": stl, "BLK": blk, "TO": to}
    for page in pdf.pages[72:74]:
        for rank, name, pos in re.findall(r"(?:^|\s)(\d+)\.\s+(.+?)\s+(PG|SG|SF|PF|C)\s+[A-Z]{2,3}\b", page.extract_text() or ""):
            if int(rank) in ranks:
                raise ValueError("Duplicate Rotoworld points rank")
            ranks[int(rank)] = {"name": name, "positions": [pos]}
    if set(ranks) != set(range(1, 201)) or len(projections) < 200:
        raise ValueError("Incomplete Rotoworld source extraction")
    return projections, ranks


def position_fields(positions):
    eligible = list(positions) + ["UTIL", "BE", "IR"]
    if set(positions) & {"PG", "SG"}:
        eligible.append("G")
    if set(positions) & {"SF", "PF"}:
        eligible.append("F")
    return {"primary": positions[0], "eligible": list(dict.fromkeys(eligible))}


def prepare(root, cfg, history_root):
    root.mkdir(parents=True, exist_ok=True)
    summaries = []
    for year, cutoff in CUTOFF.items():
        histories = {y: totals_for(y, history_root) for y in (year-2, year-1)}
        base = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/"
        def metadata(y):
            return get_json(f"{base}{y}/players?view=players_wl", history_root / "raw" / f"positions-{y}.json",
                            {"x-fantasy-filter": json.dumps({"filterActive": None})})
        prior_meta = {int(p["id"]): p for p in metadata(year-1)}
        # Target metadata supplies IDs and names only, including rookies. No other fields cross this boundary.
        identities = {key(p["fullName"]): (int(p["id"]), p["fullName"]) for p in metadata(year)}
        for rows in histories.values():
            identities.update({key(p["name"]): (pid, p["name"]) for pid, p in rows.items()})
        pdf, source = pdf_source(SHEETS[year], root / "raw" / f"espn-{year}.pdf", cutoff)
        with pdf:
            ranks = espn_ranks("\n".join(p.extract_text() or "" for p in pdf.pages), 200 if year < 2025 else 150)
        ranked, missing = {}, []
        for rank, row in ranks.items():
            identity = identities.get(key(row["name"]))
            if identity:
                ranked[identity[0]] = {"rank": rank, **row}
            else:
                missing.append(row["name"])
        if missing:
            raise ValueError(f"Unresolved preseason identities {year}: {missing}")
        projections, consensus, sources = {}, {}, [source]
        if year == 2025:
            pdf, provenance = pdf_source(NBC, root / "raw" / "rotoworld-2025.pdf", cutoff)
            with pdf:
                projections, nbc_ranks = nbc_data(pdf)
            consensus = {key(row["name"]): rank for rank, row in nbc_ranks.items()}
            for row in nbc_ranks.values():
                identity = identities.get(key(row["name"]))
                if not identity:
                    raise ValueError(f"Unresolved Rotoworld identity: {row['name']}")
                ranked.setdefault(identity[0], {"rank": None, **row})
            sources.append(provenance)
        universe = set(ranked) | set().union(*(set(rows) for rows in histories.values()))
        players, omitted, fallback = [], [], []
        for pid in sorted(universe):
            prior = prior_meta.get(pid, {})
            eligible = [SLOTS[s] for s in prior.get("eligibleSlots", []) if s in SLOTS]
            primary = SLOTS.get(prior.get("defaultPositionId", 0)-1)
            latest = histories[year-1].get(pid) or histories[year-2].get(pid)
            name = latest["name"] if latest else ranked[pid]["name"]
            if primary and set(eligible) & {"PG", "SG", "SF", "PF", "C"}:
                positions = {"primary": primary, "eligible": eligible}
            elif pid in ranked:
                positions = position_fields(ranked[pid]["positions"])
                fallback.append(pid)
            else:
                omitted.append(pid)
                continue
            players.append({"id": pid, "name": name, "team": "0", **positions, "owner": 0, "slot": "BE",
                            "status": "UNKNOWN", "availability": "FREEAGENT", "adp": None, "auction_value": None,
                            "undroppable": False, "expert_rank": ranked.get(pid, {}).get("rank"),
                            "independent_rank": consensus.get(key(name)), "preseason_projection": projections.get(key(name)),
                            "splits": [{"season": y, "source": 0, "stats": rows[pid]["stats"]} for y, rows in histories.items() if pid in rows]})
        pack = {"season": year, "cutoff": cutoff + "T00:00:00-04:00", "players": players, "sources": sources,
                "missing_positions": omitted, "published_position_fallback": fallback}
        write_json(root / f"input-{year}.json", pack)
        summaries.append({"season": year, "pool": len(players), "published": len(ranked), "position_fallback": len(fallback),
                          "omitted_positions": len(omitted), "projection_matches": sum(bool(p["preseason_projection"]) for p in players)})
        print(json.dumps(summaries[-1]), flush=True)
    return summaries


def features(model):
    year, weights = model.cfg["season"], model.cfg["scoring"]
    result = {}
    for p in model.players:
        actual = {s["season"]: s["stats"] for s in p["splits"]}
        last, older = actual.get(year-1, {}), actual.get(year-2, {})
        gp, old_gp = last.get("GP", 0), older.get("GP", 0)
        rank = p.get("expert_rank")
        result[p["id"]] = {"last": sum(last.get(k, 0)*w for k, w in weights.items()), "fpg": p["fpg"],
                            "blend": p["fpg"]*p["projected_games"], "durable": p["fpg"]*(.5*gp+.25*old_gp+.25*65),
                            "rank": rank, "screened": bool(gp or rank or p.get("independent_rank")), "no_history": not actual}
    known = sorted((r["rank"], r["blend"]) for r in result.values() if r["rank"] and not r["no_history"])
    for p in model.players:
        r = result[p["id"]]
        if r["no_history"]:
            proxy_rank = r["rank"] or p.get("independent_rank")
            neighbors = sorted(known, key=lambda a: (abs(a[0]-proxy_rank), a[0]))[:10]
            estimate = statistics.median(value for _, value in neighbors)
            r.update(durable=estimate, imputed=estimate, fpg=estimate/65)
        proj = p.get("preseason_projection")
        r["projection"] = sum(proj.get(k, 0)*w for k, w in weights.items())*proj["GP"] if proj else r["durable"]
    def ranks(field):
        return {pid: i+1 for i, pid in enumerate(sorted(result, key=lambda pid: (-result[pid][field], pid)))}
    history_rank, durable_rank, latest_rank = ranks("blend"), ranks("durable"), ranks("last")
    market = sorted(result, key=lambda pid: (result[pid]["rank"] or 1000+latest_rank[pid], pid))
    market_rank = {pid: i+1 for i, pid in enumerate(market)}
    consensus = sorted(result, key=lambda pid: ((model.by_id[pid].get("independent_rank", None) or 1000+latest_rank[pid]) +
                                               (result[pid]["rank"] or 1000+latest_rank[pid]), pid))
    consensus_rank = {pid: i+1 for i, pid in enumerate(consensus)}
    for pid, r in result.items():
        r.update(market=market_rank[pid], consensus=consensus_rank[pid], history_rank=history_rank[pid],
                 risk_rank=(durable_rank[pid]+market_rank[pid])/2,
                 blend_rank=(history_rank[pid]+market_rank[pid])/2)
        r["fit"] = max(0, 1000-r["risk_rank"])
    return result, market


def values(features, policy):
    field = {"prior_total": "last", "history_blend": "blend", "recent_gate": "blend", "per_game": "fpg",
             "durability": "durable", "expert_rank": "market", "consensus_rank": "consensus", "rank_blend": "blend_rank",
             "risk_blend": "risk_rank", "roster_fit": "risk_rank", "market_patience": "risk_rank", "projection_total": "projection"}[policy]
    ordinal = field in {"market", "consensus", "blend_rank", "risk_rank"}
    return {pid: (1000-r[field] if ordinal else r[field]) for pid, r in features.items()
            if policy in {"prior_total", "history_blend"} or r["screened"]}


def legal(model, roster, pid):
    prospective = roster + [model.by_id[pid]]
    left = roster_size(model.cfg)-len(prospective)
    return legal_roster(prospective, model.cfg) and len(active_slots(model.cfg))-len(assign(prospective, active_slots(model.cfg))) <= left


def choose(model, order, roster, gone, scores, policy, market, gap):
    choices = []
    dynamic = policy in {"roster_fit", "market_patience"}
    for pid in order:
        if pid not in gone and legal(model, roster, pid):
            choices.append(pid)
            if len(choices) >= (8 if dynamic else 1):
                break
    if not choices:
        raise ValueError("Strategy cannot complete a legal roster")
    if not dynamic:
        return choices[0]
    def objective(pid):
        proposed = roster + [model.by_id[pid]]
        if policy == "roster_fit":
            chosen = assign(proposed, active_slots(model.cfg), scores)
            return sum(scores[p["id"]]*(1 if p["id"] in chosen else .35) for p in proposed)
        if len(proposed) == roster_size(model.cfg):
            return scores[pid]
        removed = gone | {pid}
        forecast = [p for p in market if p not in removed][:gap]
        removed.update(forecast)
        future = next((p for p in order if p not in removed and legal(model, proposed, p)), None)
        return scores[pid] + .95*(scores[future] if future else 0)
    return max(choices, key=lambda pid: (objective(pid), scores[pid], -pid))


def simulate(model, target, policy, features, market, opponents):
    scores = values(features, policy)
    order = sorted(scores, key=lambda pid: (-scores[pid], pid))
    rosters = {t: [] for t in range(1, model.cfg["teams"]+1)}
    gone = set()
    teams_count, rounds = model.cfg["teams"], roster_size(model.cfg)
    for rnd in range(rounds):
        sequence = range(1, teams_count+1) if rnd % 2 == 0 else range(teams_count, 0, -1)
        for team in sequence:
            gap = 2*(teams_count-target) if rnd % 2 == 0 else 2*(target-1)
            pid = choose(model, order if team == target else opponents[team], rosters[team], gone,
                         scores, policy if team == target else "expert_rank", market, gap)
            gone.add(pid)
            rosters[team].append(model.by_id[pid])
    return {str(t): [p["id"] for p in roster] for t, roster in rosters.items()}


def source_hashes():
    return {name: hashlib.sha256(Path(__file__).with_name(name).read_text(encoding="utf-8").encode()).hexdigest()
            for name in ("strategy_lab.py", "backtest.py", "model.py", "planner.py")}


def draft(root, cfg):
    if cfg["format"] != "points":
        raise ValueError("Strategy experiment currently supports points leagues")
    evidence = {"config": {k: cfg[k] for k in ("teams", "slots", "position_limits", "scoring", "format")},
                "source_sha256": source_hashes(), "inputs": {}, "cases": []}
    for year in CUTOFF:
        pack = read_json(root / f"input-{year}.json")
        if pack["season"] != year or pack["cutoff"][:10] != CUTOFF[year]:
            raise ValueError("Historical input season/cutoff mismatch")
        evidence["inputs"][str(year)] = digest(pack)
        model = input_model(cfg, pack)
        feature, market = features(model)
        policies = list(STRATEGIES) + (["consensus_rank", "projection_total"] if year == 2025 else [])
        prior = sorted(feature, key=lambda pid: (-feature[pid]["last"], pid))
        prior_rank = {pid: i+1 for i, pid in enumerate(prior)}
        market_rank = {pid: i+1 for i, pid in enumerate(market)}
        pool = [pid for pid in market if feature[pid]["screened"]]
        for family in ("expert", "mixed", "prior"):
            base = {pid: market_rank[pid] if family == "expert" else prior_rank[pid] if family == "prior" else
                         (market_rank[pid]+prior_rank[pid])/2 for pid in pool}
            for seed in (-1, 0, 1):
                opponents = {}
                for team in range(1, cfg["teams"]+1):
                    rng = random.Random(f"strategy:{year}:{family}:{seed}:{team}")
                    noise = {pid: rng.gauss(0, 12) if seed >= 0 else 0 for pid in pool}
                    opponents[team] = sorted(pool, key=lambda pid: (base[pid]+noise[pid], pid))
                for slot in range(1, cfg["teams"]+1):
                    for policy in policies:
                        rosters = simulate(model, slot, policy, feature, pool, opponents)
                        evidence["cases"].append({"season": year, "family": family, "seed": seed, "slot": slot,
                                                  "strategy": policy, "rosters": rosters})
                print(json.dumps({"drafted": year, "family": family, "seed": seed, "cases": len(evidence["cases"])}), flush=True)
    write_json(root / "decisions.json", evidence)
    checksum = digest(evidence)
    (root / "decisions.sha256").write_text(checksum+"\n")
    return {"drafts": len(evidence["cases"]), "decision_sha256": checksum}


def locked(root):
    evidence = read_json(root / "decisions.json")
    if digest(evidence) != (root / "decisions.sha256").read_text().strip() or evidence["source_sha256"] != source_hashes():
        raise ValueError("Decisions or source changed after locking")
    for year, checksum in evidence["inputs"].items():
        if digest(read_json(root / f"input-{year}.json")) != checksum:
            raise ValueError("Inputs changed after locking")
    return evidence


def grade(model, roster, outcomes):
    points, games = {}, {}
    for pid in roster:
        stats = outcomes.get(pid, {"stats": {"GP": 0}})["stats"]
        points[pid] = sum(stats.get(k, 0)*v for k, v in model.cfg["scoring"].items())
        games[pid] = stats["GP"]
    lineup = assign([model.by_id[pid] for pid in roster], active_slots(model.cfg), points)
    return {"total": sum(points.values()), "starting_nine": sum(points[pid] for pid in lineup),
            "zero_games": sum(g == 0 for g in games.values()), "low_games": sum(g < 25 for g in games.values())}


def score(root, cfg, history_root, phase):
    evidence = locked(root)
    selection = read_json(root / "selection.json")
    if phase == "test" and (not selection or selection["decision_sha256"] != digest(evidence) or
                            digest(selection) != (root / "selection.sha256").read_text().strip()):
        raise ValueError("Freeze development selection before reading held-out outcomes")
    cfg = copy.deepcopy(cfg)
    cfg.update(evidence["config"])
    years = DEVELOP if phase == "develop" else (TEST,)
    models = {year: input_model(cfg, read_json(root / f"input-{year}.json")) for year in years}
    outcomes = {year: totals_for(year, history_root) for year in years}
    rows = []
    for case in evidence["cases"]:
        year = case["season"]
        if year not in years:
            continue
        target = case["slot"]
        grades = {int(t): grade(models[year], roster, outcomes[year]) for t, roster in case["rosters"].items()}
        ours = grades[target]
        finish = 1 + sum(g["starting_nine"] > ours["starting_nine"] for t, g in grades.items() if t != target)
        rows.append({**{k: case[k] for k in ("season", "family", "seed", "slot", "strategy")}, **ours, "finish": finish})
    baseline = {(r["season"], r["family"], r["seed"], r["slot"]): r for r in rows if r["strategy"] == "expert_rank"}
    for r in rows:
        b = baseline[(r["season"], r["family"], r["seed"], r["slot"])]
        r["gain_pct"] = 100*(r["starting_nine"]-b["starting_nine"])/b["starting_nine"]
        r["roster_gain_pct"] = 100*(r["total"]-b["total"])/b["total"]
        r["win"] = r["starting_nine"] > b["starting_nine"]
    summary = []
    for year, family, strategy in sorted({(r["season"], r["family"], r["strategy"]) for r in rows}):
        group = [r for r in rows if (r["season"], r["family"], r["strategy"]) == (year, family, strategy)]
        summary.append({"season": year, "family": family, "strategy": strategy, "drafts": len(group),
                        **{k: round(statistics.mean(r[k] for r in group), 3) for k in
                           ("total", "starting_nine", "gain_pct", "roster_gain_pct", "zero_games", "low_games", "finish", "win")},
                        "gain_p10": round(sorted(r["gain_pct"] for r in group)[int(.1*len(group))], 3),
                        "gain_p90": round(sorted(r["gain_pct"] for r in group)[int(.9*len(group))], 3)})
    result = {"decision_sha256": digest(evidence), "phase": phase, "summary": summary, "rows": rows}
    if phase == "develop":
        candidates = {strategy: statistics.mean(r["gain_pct"] for r in summary if r["strategy"] == strategy and r["family"] != "prior")
                      for strategy in STRATEGIES}
        chosen = max(candidates, key=lambda s: (candidates[s], s))
        new_selection = {"strategy": chosen, "decision_sha256": digest(evidence), "development_scores": candidates,
                         "criterion": "mean season/field starting-nine gain vs expert; expert/mixed only"}
        if selection and selection != new_selection:
            raise ValueError("Existing frozen selection disagrees; do not overwrite it")
        write_json(root / "selection.json", new_selection)
        (root / "selection.sha256").write_text(digest(new_selection)+"\n")
        result["selection"] = new_selection
    else:
        result["selection"] = selection
    write_json(root / f"results-{phase}.json", result)
    return {k: v for k, v in result.items() if k != "rows"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("prepare", "draft", "develop", "test"))
    p.add_argument("--root", type=Path, default=Path("basketball/data/strategy-lab"))
    p.add_argument("--history-root", type=Path, default=Path("basketball/data/backtest"))
    p.add_argument("--config")
    args = p.parse_args()
    cfg = load(args.config)
    result = prepare(args.root, cfg, args.history_root) if args.action == "prepare" else draft(args.root, cfg) if args.action == "draft" else score(args.root, cfg, args.history_root, args.action)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
