"""Project 2026-27 fantasy points for league 23491 (Yahoo H2H points) from the
last two NHL seasons, then rank by value over replacement (VOR)."""
import csv
import json
from collections import defaultdict
from pathlib import Path

RAW = Path("data/raw")
SEASONS = {"20252026": 0.65, "20242025": 0.35}  # recency weights

SKATER_PTS = dict(G=6, A=4, PM=0.1, PIM=-0.2, SHG=0.25, SHA=0.15, SOG=0.1, FW=0.2, FL=-0.1, HIT=0.5, BLK=0.75)
GOALIE_PTS = dict(W=2, L=-0.5, GA=-3, SV=0.6, SHO=2)

# Rostered-at-position depth in a 12-team league (starters + share of bench).
REPLACEMENT_RANK = {"C": 30, "LW": 30, "RW": 30, "D": 56, "G": 26}
POS = {"C": "C", "L": "LW", "R": "RW", "D": "D"}


def load(kind, report, season):
    return {r["playerId"]: r for r in json.loads((RAW / f"{kind}_{report}_{season}.json").read_text())}


def skater_season_fp(s, rt, fo):
    shp = s["shPoints"] or 0
    shg = s["shGoals"] or 0
    return (
        SKATER_PTS["G"] * s["goals"] + SKATER_PTS["A"] * s["assists"] + SKATER_PTS["PM"] * s["plusMinus"]
        + SKATER_PTS["PIM"] * s["penaltyMinutes"] + SKATER_PTS["SHG"] * shg + SKATER_PTS["SHA"] * (shp - shg)
        + SKATER_PTS["SOG"] * s["shots"] + SKATER_PTS["FW"] * (fo.get("totalFaceoffWins") or 0)
        + SKATER_PTS["FL"] * (fo.get("totalFaceoffLosses") or 0)
        + SKATER_PTS["HIT"] * (rt.get("hits") or 0) + SKATER_PTS["BLK"] * (rt.get("blockedShots") or 0)
    )


def goalie_season_fp(g):
    return (GOALIE_PTS["W"] * g["wins"] + GOALIE_PTS["L"] * g["losses"] + GOALIE_PTS["GA"] * g["goalsAgainst"]
            + GOALIE_PTS["SV"] * g["saves"] + GOALIE_PTS["SHO"] * g["shutouts"])


def blend(per_season):
    """per_season: list of (weight, gp, fp, extra) -> weighted FP/G and projected GP."""
    wsum = sum(w * gp for w, gp, _, _ in per_season)
    fpg = sum(w * fp for w, _, fp, _ in per_season) / wsum if wsum else 0
    # games played: lean harder on the most recent season than scoring does
    gp_w = {"20252026": 0.8, "20242025": 0.2}
    wgp = sum(gp_w[s] * gp for _, gp, _, s in per_season) / sum(gp_w[s] for *_, s in per_season)
    return fpg, wgp


def main():
    players = defaultdict(lambda: {"seasons": []})
    for season, w in SEASONS.items():
        summ, rt, fo = load("skater", "summary", season), load("skater", "realtime", season), load("skater", "faceoffwins", season)
        for pid, s in summ.items():
            fp = skater_season_fp(s, rt.get(pid, {}), fo.get(pid, {}))
            p = players[pid]
            p.update(name=s["skaterFullName"], pos=POS[s["positionCode"]], team=s["teamAbbrevs"].split(",")[-1])
            if season == "20252026" or "last" not in p:
                p["last"] = dict(season=season, gp=s["gamesPlayed"], g=s["goals"], a=s["assists"], sog=s["shots"],
                                 hit=rt.get(pid, {}).get("hits"), blk=rt.get(pid, {}).get("blockedShots"),
                                 fw=fo.get(pid, {}).get("totalFaceoffWins"), toi=round((s["timeOnIcePerGame"] or 0) / 60, 1))
            p["seasons"].append((w, s["gamesPlayed"], fp, season))
        for pid, g in load("goalie", "summary", season).items():
            p = players[pid]
            p.update(name=g["goalieFullName"], pos="G", team=g["teamAbbrevs"].split(",")[-1])
            if season == "20252026" or "last" not in p:
                p["last"] = dict(season=season, gp=g["gamesPlayed"], gs=g["gamesStarted"], w=g["wins"],
                                 svp=g["savePct"], gaa=g["goalsAgainstAverage"], sv=g["saves"])
            p["seasons"].append((w, g["gamesStarted"] or g["gamesPlayed"], goalie_season_fp(g), season))

    # Manual overrides from offseason research: {name: {team, proj_gp, fpg_mult, note}}
    adj_path = Path("data/adjustments.json")
    adjustments = json.loads(adj_path.read_text()) if adj_path.exists() else {}

    out = []
    for pid, p in players.items():
        seasons = p["seasons"]
        total_gp = sum(gp for _, gp, _, _ in seasons)
        if total_gp < 20:
            continue
        fpg, wgp = blend(seasons)
        if p["pos"] == "G":
            proj_gp = min(62, max(15, wgp))  # starts
        else:
            # one injury-shortened year shouldn't sink a player; cap at 80
            proj_gp = min(80, max(60 if total_gp >= 100 else 40, wgp))
        # small-sample regression toward a modest baseline
        if total_gp < 60:
            fpg *= 0.85 + 0.15 * total_gp / 60
        a = adjustments.get(p["name"], {})
        if a.get("remove"):
            continue
        fpg *= a.get("fpg_mult", 1.0)
        proj_gp = a.get("proj_gp", proj_gp)
        out.append(dict(pid=pid, name=p["name"], pos=p["pos"], team=a.get("team", p["team"]), fpg=round(fpg, 2),
                        proj_gp=round(proj_gp), proj_fp=round(fpg * proj_gp, 1), last=p["last"], note=a.get("note", "")))

    by_pos = defaultdict(list)
    for r in out:
        by_pos[r["pos"]].append(r)
    for pos, rows in by_pos.items():
        rows.sort(key=lambda r: -r["proj_fp"])
        repl = rows[min(REPLACEMENT_RANK[pos], len(rows)) - 1]["proj_fp"]
        for i, r in enumerate(rows, 1):
            r["pos_rank"] = f"{pos}{i}"
            r["vor"] = round(r["proj_fp"] - repl, 1)
            r["repl"] = repl
    out.sort(key=lambda r: -r["vor"])

    Path("data").mkdir(exist_ok=True)
    with open("data/rankings.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "name", "pos", "pos_rank", "team", "proj_fp", "vor", "fpg", "proj_gp", "note", "last_season"])
        for i, r in enumerate(out, 1):
            w.writerow([i, r["name"], r["pos"], r["pos_rank"], r["team"], r["proj_fp"], r["vor"], r["fpg"], r["proj_gp"], r["note"], json.dumps(r["last"])])
    print("replacement FP:", {p: rows[min(REPLACEMENT_RANK[p], len(rows)) - 1]["proj_fp"] for p, rows in by_pos.items()})
    for i, r in enumerate(out[:200], 1):
        l = r["last"]
        extra = (f"GS {l.get('gs')} SV% {l.get('svp') and round(l['svp'],3)} W {l.get('w')}" if r["pos"] == "G"
                 else f"{l['g']}G {l['a']}A {l['sog']}SOG {l['hit']}H {l['blk']}B {l['fw']}FW {l['toi']}toi")
        print(f"{i:3} {r['name']:24} {r['pos_rank']:5} {r['team']:4} FP {r['proj_fp']:6} VOR {r['vor']:6} FP/G {r['fpg']:5} GP {r['proj_gp']:2} | {l['season'][4:]} GP{l['gp']} {extra}")


if __name__ == "__main__":
    main()
