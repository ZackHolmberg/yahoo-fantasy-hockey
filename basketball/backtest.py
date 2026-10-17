"""Chronological history-only draft holdouts. Selection never receives outcomes.

Run prepare -> draft -> score. Draft decisions are hashed before scoring.
See docs/BASKETBALL_BACKTEST_PROTOCOL.md for the registered limitations.
"""
import argparse
import copy
import hashlib
import io
import json
import math
from pathlib import Path
import random
import re
import statistics
import tempfile
import urllib.request

from .config import SLOTS, active_slots, load, read_json, roster_size, write_json
from .drafting import board
from .model import Model
from .planner import assign, legal_roster

BASE = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/statistics/byathlete"
FIELDS = {"gamesPlayed": "GP", "points": "PTS", "fieldGoalsMade": "FGM", "fieldGoalsAttempted": "FGA",
          "freeThrowsMade": "FTM", "freeThrowsAttempted": "FTA", "threePointFieldGoalsMade": "3PM",
          "rebounds": "REB", "assists": "AST", "steals": "STL", "blocks": "BLK", "turnovers": "TO"}
ARCHIVES = {
    2023: "https://g.espncdn.com/s/fbadraftkit/2022-2023/FBA2022CSpts.pdf",
    2025: "https://g.espncdn.com/s/fbadraftkit/2024-25/FBA24ptsCS.pdf",
}
FROZEN_STRATEGY = "2c349c156a8b82825e0ca241b0f66501751b605f"
CUTOFFS = {2020: "2019-10-21", 2023: "2022-10-17", 2024: "2023-10-23", 2025: "2024-10-21"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def get_json(url, filename, headers=None):
    if filename.exists():
        return read_json(filename)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=45) as response:
        value = json.load(response)
    write_json(filename, value)
    return value


def parse_totals(raw, year):
    season = raw.get("requestedSeason", {})
    pagination = raw.get("pagination", {})
    rows = raw.get("athletes", [])
    if season.get("year") != year or season.get("type", {}).get("type") != 2:
        raise ValueError("Statistics response is for a different season/type")
    if pagination.get("pages") != 1 or pagination.get("count") != len(rows):
        raise ValueError("Incomplete NBA outcome/input feed; no missing players may be treated as zero")
    names = {c["name"]: c["names"] for c in raw["categories"]}
    result = {}
    for row in rows:
        pid = int(row["athlete"]["id"])
        if pid in result:
            raise ValueError("Duplicate athlete in statistics feed")
        stats = {}
        for category in row["categories"]:
            labels, values = names[category["name"]], category["values"]
            if len(labels) != len(values):
                raise ValueError("NBA statistics schema changed")
            stats.update({FIELDS[k]: float(v) for k, v in zip(labels, values) if k in FIELDS})
        if set(stats) != set(FIELDS.values()) or stats["GP"] <= 0 or not all(math.isfinite(v) and v >= 0 for v in stats.values()):
            raise ValueError("Missing regular-season totals for a returned athlete")
        result[pid] = {"id": pid, "name": row["athlete"]["displayName"], "stats": stats}
    return result


def totals_for(year, root):
    url = f"{BASE}?season={year}&seasontype=2&limit=1000&isqualified=false"
    raw = get_json(url, root / "raw" / f"totals-{year}.json")
    return parse_totals(raw, year)


def name_key(name):
    from .drafting import normalize_name
    key = re.sub(r"[^a-z0-9]", "", normalize_name(name))
    # Identity-only aliases; never use season performance to resolve names.
    return {"jimmybutleriii": "jimmybutler", "nicolasclaxton": "nicclaxton",
            "paulobanchero": "paolobanchero", "benedictmathurin": "bennedictmathurin"}.get(key, key)


def archived_board(year, root):
    if year not in ARCHIVES:
        return None
    filename = root / "raw" / f"preseason-{year}.pdf"
    if not filename.exists():
        filename.parent.mkdir(parents=True, exist_ok=True)
        filename.write_bytes(urllib.request.urlopen(ARCHIVES[year], timeout=30).read())
    try:
        import pdfplumber
    except ImportError as exc:
        raise ValueError("Install pdfplumber to extract the optional archived ESPN comparison") from exc
    with pdfplumber.open(io.BytesIO(filename.read_bytes())) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    # Ignore team/position columns: the PDFs contain some incorrect assignments.
    # Historical position eligibility comes exclusively from last season's API.
    rows = re.findall(r"(?:^|\s)(\d+)\.\s+([^,\n]+),", text)
    ranks = {int(rank): name.strip() for rank, name in rows}
    expected = 200 if year == 2023 else 150
    if set(ranks) != set(range(1, expected + 1)):
        raise ValueError("Archived preseason rank extraction is incomplete")
    return {"url": ARCHIVES[year], "sha256": hashlib.sha256(filename.read_bytes()).hexdigest(),
            "ranks": ranks, "cutoff": expected}


def prepare(root, seasons):
    root.mkdir(parents=True, exist_ok=True)
    summaries = []
    for year in seasons:
        histories = {y: totals_for(y, root) for y in (year - 2, year - 1)}
        url = f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{year-1}/players?view=players_wl"
        metadata = get_json(url, root / "raw" / f"positions-{year-1}.json",
                            {"x-fantasy-filter": json.dumps({"filterActive": None})})
        meta = {int(p["id"]): p for p in metadata}
        universe = set().union(*(rows.keys() for rows in histories.values()))
        players, missing_positions = [], []
        for pid in sorted(universe):
            p = meta.get(pid, {})
            eligible = [SLOTS[s] for s in p.get("eligibleSlots", []) if s in SLOTS]
            primary = SLOTS.get(p.get("defaultPositionId", 0) - 1)
            if not primary or not set(eligible) & {"PG", "SG", "SF", "PF", "C"}:
                missing_positions.append(pid)
                continue
            latest = histories[year-1].get(pid) or histories[year-2][pid]
            players.append({"id": pid, "name": latest["name"], "team": str(p.get("proTeamId", 0)),
                            "primary": primary, "eligible": eligible, "owner": 0, "slot": "BE",
                            "status": "UNKNOWN", "undroppable": False, "availability": "FREEAGENT",
                            "adp": None, "auction_value": None,
                            "splits": [{"season": y, "source": 0, "stats": rows[pid]["stats"]}
                                       for y, rows in histories.items() if pid in rows]})
        archive = archived_board(year, root)
        pack = {"season": year, "cutoff": CUTOFFS.get(year, f"{year-1}-09-01") + "T00:00:00-04:00", "players": players,
                "archive": archive, "missing_prior_positions": missing_positions,
                "sources": {"stats": [f"{BASE}?season={y}&seasontype=2&limit=1000&isqualified=false" for y in histories], "positions": url}}
        write_json(root / f"input-{year}.json", pack)
        summaries.append({"season": year, "pool": len(players), "missing_positions": len(missing_positions),
                          "archive_cutoff": archive["cutoff"] if archive else None})
        print(json.dumps(summaries[-1]), flush=True)
    return summaries


def input_model(cfg, pack):
    year = pack["season"]
    if any(s["season"] >= year or s["source"] != 0 for p in pack["players"] for s in p["splits"]):
        raise ValueError("Future information in draft inputs")
    cfg = copy.deepcopy(cfg)
    cfg.update(season=year, team_id=1, adjustments={})
    cfg["draft"].update(type="snake", slot=1)
    snap = {"league_id": cfg["league_id"], "team_id": 1, "season": year, "fetched_at": pack["cutoff"],
            "source": "historical-priors-only", "players": pack["players"], "games": {}, "teams": [], "draft": {}}
    return Model(cfg, snap)


def legal_choice(model, order, roster, gone):
    cfg, slots = model.cfg, active_slots(model.cfg)
    remaining = roster_size(cfg) - len(roster)
    for pid in order:
        if pid in gone:
            continue
        prospective = [dict(p, slot="BE") for p in roster + [model.by_id[pid]]]
        if legal_roster(prospective, cfg) and len(slots) - len(assign(prospective, slots)) <= remaining - 1:
            return pid
    raise ValueError("No legal selection remains in the historical pool")


def simulate(base_model, slot, target_order, opponents):
    """target_order=None exercises the production draft board unchanged."""
    model = copy.copy(base_model)
    model.cfg = copy.deepcopy(base_model.cfg)
    model.cfg.update(team_id=slot)
    model.cfg["draft"]["slot"] = slot
    rosters = {t: [] for t in range(1, model.cfg["teams"] + 1)}
    picks, gone = [], set()
    with tempfile.TemporaryDirectory(prefix="basketball-backtest-") as temp:
        model.cfg["_data"] = temp
        for round_id in range(roster_size(model.cfg)):
            teams = range(1, model.cfg["teams"] + 1) if round_id % 2 == 0 else range(model.cfg["teams"], 0, -1)
            for team in teams:
                overall = len(picks) + 1
                if team == slot and target_order is None:
                    write_json(Path(temp) / "draft.json", {"picks": picks})
                    choices = board(model, count=1, current=overall)["players"]
                    if not choices:
                        raise ValueError("Production board could not complete a historical roster")
                    pid = choices[0]["id"]
                else:
                    pid = legal_choice(model, target_order if team == slot else opponents[team], rosters[team], gone)
                gone.add(pid)
                rosters[team].append(model.by_id[pid])
                picks.append({"player": pid, "team": team, "pick": overall, "cost": 0, "source": "backtest"})
    return picks


def prior_order(model):
    def score(p):
        split = next((s for s in p["splits"] if s["season"] == model.cfg["season"] - 1), None)
        return sum(split["stats"].get(k, 0) * v for k, v in model.cfg["scoring"].items()) if split else 0
    return [p["id"] for p in sorted(model.players, key=lambda p: (-score(p), p["id"]))]


def archive_order(pack, model, prior):
    by_name = {name_key(p["name"]): p["id"] for p in model.players}
    matched, unmatched = [], []
    for _, name in sorted(pack["archive"]["ranks"].items(), key=lambda item: int(item[0])):
        key = name_key(name)
        if key in by_name:
            matched.append(by_name[key])
        else:
            unmatched.append(name)
    if len(set(matched)) != len(matched):
        raise ValueError("Duplicate identity in archived preseason ranks")
    return matched + [pid for pid in prior if pid not in set(matched)], unmatched


def draft(root, seasons, cfg, seeds=5):
    if cfg["format"] != "points":
        raise ValueError("This historical experiment evaluates points leagues only")
    cases, inputs, unmatched = [], {}, {}
    for year in seasons:
        pack = read_json(root / f"input-{year}.json")
        inputs[str(year)] = digest(pack)
        model = input_model(cfg, pack)
        prior = prior_order(model)
        comparisons = {"prior_points": prior}
        if pack.get("archive"):
            comparisons["espn_archive_hybrid"], unmatched[str(year)] = archive_order(pack, model, prior)
        for seed in [-1] + list(range(seeds)):
            opponents = {}
            rank = {pid: i for i, pid in enumerate(prior)}
            for team in range(1, cfg["teams"] + 1):
                rng = random.Random(f"{year}:{seed}:{team}")
                opponents[team] = sorted(prior, key=lambda pid: rank[pid] + (rng.gauss(0, 8) if seed >= 0 else 0))
            for slot in range(1, cfg["teams"] + 1):
                ours = simulate(model, slot, None, opponents)
                for comparison, order in comparisons.items():
                    baseline = simulate(model, slot, order, opponents)
                    cases.append({"season": year, "seed": seed, "slot": slot, "comparison": comparison,
                                  "model": ours, "baseline": baseline})
            print(json.dumps({"drafted_season": year, "seed": seed, "paired_cases": len(cases)}), flush=True)
    # Owner overrides are deliberately absent from the registered experiment.
    source_hashes = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                     for name in ("model.py", "drafting.py", "backtest.py")}
    evidence = {"strategy_commit": FROZEN_STRATEGY, "source_sha256": source_hashes, "config": {k: cfg[k] for k in ("teams", "slots", "position_limits", "scoring", "format")},
                "input_sha256": inputs, "unmatched_archive_names": unmatched, "seeds": seeds, "cases": cases}
    write_json(root / "decisions.json", evidence)
    checksum = digest(evidence)
    (root / "decisions.sha256").write_text(checksum + "\n", encoding="utf-8")
    return {"paired_cases": len(cases), "sha256": checksum}


def evaluate_picks(picks, slot, model, outcomes):
    roster = []
    for pick in picks:
        if pick["team"] != slot:
            continue
        p = model.by_id[pick["player"]]
        actual = outcomes.get(p["id"], {"stats": {"GP": 0}})["stats"]
        points = sum(actual.get(k, 0) * w for k, w in model.cfg["scoring"].items())
        roster.append({"id": p["id"], "name": p["name"], "eligible": p["eligible"], "value": points,
                       "games": actual["GP"], "pick": pick["pick"]})
    lineup = assign(roster, active_slots(model.cfg))
    return {"total": sum(p["value"] for p in roster), "starting_nine": sum(p["value"] for p in roster if p["id"] in lineup),
            "zero_games": sum(p["games"] == 0 for p in roster), "low_games": sum(p["games"] < 25 for p in roster), "roster": roster}


def score(root, cfg):
    evidence = read_json(root / "decisions.json")
    expected = (root / "decisions.sha256").read_text().strip()
    if digest(evidence) != expected:
        raise ValueError("Draft decisions changed after locking")
    for name, checksum in evidence.get("source_sha256", {}).items():
        if hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() != checksum:
            raise ValueError("Backtest or strategy source changed after locking")
    frozen = copy.deepcopy(cfg)
    frozen.update(evidence["config"])
    models, outcomes = {}, {}
    for year_text, checksum in evidence["input_sha256"].items():
        year = int(year_text)
        pack = read_json(root / f"input-{year}.json")
        if digest(pack) != checksum:
            raise ValueError("Historical inputs changed after locking")
        models[year] = input_model(frozen, pack)
        outcomes[year] = totals_for(year, root)
    scored = []
    for case in evidence["cases"]:
        year = case["season"]
        scored.append({**{k: case[k] for k in ("season", "seed", "slot", "comparison")},
                       **{arm: evaluate_picks(case[arm], case["slot"], models[year], outcomes[year]) for arm in ("model", "baseline")}})
    summary = []
    for year, comparison in sorted({(r["season"], r["comparison"]) for r in scored}):
        rows = [r for r in scored if r["season"] == year and r["comparison"] == comparison]
        summary.append({"season": year, "comparison": comparison, "pairs": len(rows),
                        "model_points": round(statistics.mean(r["model"]["total"] for r in rows), 1),
                        "baseline_points": round(statistics.mean(r["baseline"]["total"] for r in rows), 1),
                        "mean_gain_pct": round(100 * statistics.mean((r["model"]["total"] - r["baseline"]["total"]) / r["baseline"]["total"] for r in rows), 2),
                        "win_rate": round(statistics.mean(r["model"]["total"] > r["baseline"]["total"] for r in rows), 3),
                        "starting_nine_gain_pct": round(100 * statistics.mean((r["model"]["starting_nine"] - r["baseline"]["starting_nine"]) / r["baseline"]["starting_nine"] for r in rows), 2),
                        "model_zero_games_per_team": round(statistics.mean(r["model"]["zero_games"] for r in rows), 2),
                        "baseline_zero_games_per_team": round(statistics.mean(r["baseline"]["zero_games"] for r in rows), 2)})
    result = {"decision_sha256": expected, "strategy_commit": FROZEN_STRATEGY, "scope": "history-fallback chronological holdout; season-total proxies only",
              "summary": summary, "cases": scored, "unmatched_archive_names": evidence["unmatched_archive_names"]}
    write_json(root / "results.json", result)
    return {k: v for k, v in result.items() if k != "cases"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("prepare", "draft", "score"))
    p.add_argument("--config")
    p.add_argument("--root", default="basketball/data/backtest")
    p.add_argument("--seasons", nargs="+", type=int, default=[2020, 2023, 2024, 2025])
    p.add_argument("--seeds", type=int, default=5)
    args = p.parse_args()
    cfg, root = load(args.config), Path(args.root)
    result = prepare(root, args.seasons) if args.action == "prepare" else draft(root, args.seasons, cfg, args.seeds) if args.action == "draft" else score(root, cfg)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
