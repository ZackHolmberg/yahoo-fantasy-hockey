"""Backtest the draft strategy on past seasons.

For each target season we build projections using ONLY the two prior seasons,
simulate a 12-team snake draft (league 23491 roster rules) against opponent
bots, then score every roster on what actually happened in the target season.
"""
import random
import statistics
import sys
from collections import defaultdict

from project import GOALIE_PTS, POS, load, goalie_season_fp, skater_season_fp

TEAMS, ROUNDS = 12, 17
MIN_NEED = {"C": 2, "LW": 2, "RW": 2, "D": 4, "G": 2}
CAPS = {"C": 4, "LW": 4, "RW": 4, "D": 6, "G": 3}
STARTERS = {"C": 2, "LW": 2, "RW": 2, "D": 4, "G": 1}
REPL = {"C": 30, "LW": 30, "RW": 30, "D": 56, "G": 26}


def season_table(season):
    """playerId -> dict(name,pos,gp,fp,pts,wins) for one season."""
    out = {}
    summ, rt, fo = load("skater", "summary", season), load("skater", "realtime", season), load("skater", "faceoffwins", season)
    for pid, s in summ.items():
        out[pid] = dict(name=s["skaterFullName"], pos=POS[s["positionCode"]], gp=s["gamesPlayed"],
                        fp=skater_season_fp(s, rt.get(pid, {}), fo.get(pid, {})), pts=s["points"], wins=0)
    for pid, g in load("goalie", "summary", season).items():
        out[pid] = dict(name=g["goalieFullName"], pos="G", gp=g["gamesStarted"] or g["gamesPlayed"],
                        fp=goalie_season_fp(g), pts=0, wins=g["wins"])
    return out


def project(recent, prev):
    """Same method as project.py: 65/35 FP/G blend, GP leaning 80/20 on recent."""
    rows = {}
    for pid in set(recent) | set(prev):
        seas = [(w, t[pid]) for w, t in ((0.65, recent), (0.35, prev)) if pid in t]
        gp_tot = sum(r["gp"] for _, r in seas)
        if gp_tot < 20:
            continue
        wgp = sum(w * r["gp"] for w, r in seas)
        fpg = sum(w * r["fp"] for w, r in seas) / wgp if wgp else 0
        gpw = {0.65: 0.8, 0.35: 0.2}
        pgp = sum(gpw[w] * r["gp"] for w, r in seas) / sum(gpw[w] for w, _ in seas)
        info = (recent.get(pid) or prev.get(pid))
        if info["pos"] == "G":
            pgp = min(62, max(15, pgp))
        else:
            pgp = min(80, max(60 if gp_tot >= 100 else 40, pgp))
        if gp_tot < 60:
            fpg *= 0.85 + 0.15 * gp_tot / 60
        # "public" value: what a typical manager drafts on (real-life points / goalie wins)
        ppg = sum(w * r["pts"] for w, r in seas) / wgp if wgp else 0
        wpg = sum(w * r["wins"] for w, r in seas) / wgp if wgp else 0
        public = (wpg * pgp * 2.4) if info["pos"] == "G" else ppg * pgp
        rows[pid] = dict(pid=pid, name=info["name"], pos=info["pos"], proj=fpg * pgp, public=public)
    by_pos = defaultdict(list)
    for r in rows.values():
        by_pos[r["pos"]].append(r)
    for pos, lst in by_pos.items():
        lst.sort(key=lambda r: -r["proj"])
        repl = lst[min(REPL[pos], len(lst)) - 1]["proj"]
        for r in lst:
            r["vor"] = r["proj"] - repl
    return rows


def legal(roster, pos, picks_left):
    have = defaultdict(int)
    for r in roster:
        have[r["pos"]] += 1
    if have[pos] >= CAPS[pos]:
        return False
    unmet = sum(max(0, MIN_NEED[p] - have[p]) for p in MIN_NEED)
    if unmet >= picks_left:  # must fill a needed slot
        return have[pos] < MIN_NEED[pos]
    return True


def choose(strategy, avail, roster, picks_left, rnd, rng):
    def ok(r):
        return legal(roster, r["pos"], picks_left)
    cands = [r for r in avail if ok(r)]
    if strategy == "vor":
        key = lambda r: r["vor"]
    elif strategy == "vor_g_late":
        cands = [r for r in cands if r["pos"] != "G" or rnd >= 6] or cands
        key = lambda r: r["vor"]
    elif strategy == "vor_1g_early":
        # one goalie by round 3, second by round 8, else pure VOR
        ng = sum(r["pos"] == "G" for r in roster)
        if (ng == 0 and rnd >= 3) or (ng == 1 and rnd >= 8):
            cands = [r for r in cands if r["pos"] == "G"] or cands
        key = lambda r: r["vor"]
    elif strategy == "vor_gdisc":
        # value a goalie by how much of him actually reaches the single G slot
        ng = sum(r["pos"] == "G" for r in roster)
        mult = (1.0, 0.5, 0.2, 0.0)[min(ng, 3)]
        key = lambda r: r["vor"] * mult if r["pos"] == "G" else r["vor"]
    elif strategy == "raw":
        key = lambda r: r["proj"]
    elif strategy == "public":
        key = lambda r: r["public_noisy"]
    elif strategy == "savvy":  # league-aware opponent: raw FP with noise
        key = lambda r: r["proj_noisy"]
    return max(cands, key=key)


def score(roster, actual):
    """Season FP of best lineup + partial credit for bench fill-ins (daily league)."""
    by_pos = defaultdict(list)
    for r in roster:
        by_pos[r["pos"]].append(actual.get(r["pid"], {}).get("fp", 0.0))
    total = 0.0
    for pos, vals in by_pos.items():
        vals.sort(reverse=True)
        n = STARTERS[pos]
        if pos == "G":
            total += sum(v * w for v, w in zip(vals, (1.0, 0.5, 0.2)))
        else:
            total += sum(vals[:n]) + 0.25 * sum(vals[n:])
    return total


def simulate(rows, actual, my_strategy, my_slot, opp_strategy, rng):
    pool = []
    for r in rows:
        r = dict(r)
        r["public_noisy"] = r["public"] * rng.lognormvariate(0, 0.12)
        r["proj_noisy"] = r["proj"] * rng.lognormvariate(0, 0.12)
        pool.append(r)
    rosters = [[] for _ in range(TEAMS)]
    for rnd in range(ROUNDS):
        order = range(TEAMS) if rnd % 2 == 0 else reversed(range(TEAMS))
        for t in order:
            strat = my_strategy if t == my_slot else opp_strategy
            pick = choose(strat, pool, rosters[t], ROUNDS - rnd, rnd, rng)
            rosters[t].append(pick)
            pool.remove(pick)
    scores = [score(r, actual) for r in rosters]
    mine = scores[my_slot]
    return dict(rank=1 + sum(s > mine for s in scores), mine=mine, best_other=max(s for i, s in enumerate(scores) if i != my_slot),
                median=statistics.median(scores))


def main():
    targets = {"20242025": ("20232024", "20222023"), "20252026": ("20242025", "20232024")}
    strategies = sys.argv[1:] or ["vor", "vor_1g_early", "vor_g_late", "raw", "public"]
    seeds = 6
    for opp in ("public", "savvy"):
        print(f"\n=== Opponents draft '{opp}' ({'real-life points / goalie wins' if opp == 'public' else 'league-scoring FP, raw'}) ===")
        for tgt, (rec, prv) in targets.items():
            rows = project(season_table(rec), season_table(prv))
            # nobody drafts outside the top ~350 on either list; trim for speed
            keep = set(sorted(rows, key=lambda k: -rows[k]["proj"])[:350]) | set(sorted(rows, key=lambda k: -rows[k]["public"])[:350])
            rows = [rows[k] for k in keep]
            actual = season_table(tgt)
            print(f"-- Target season {tgt[:4]}-{tgt[6:]}")
            for strat in strategies:
                res = [simulate(rows, actual, strat, slot, opp, random.Random(seed * 100 + slot))
                       for slot in range(TEAMS) for seed in range(seeds)]
                ranks = [r["rank"] for r in res]
                win = sum(r == 1 for r in ranks) / len(ranks)
                top3 = sum(r <= 3 for r in ranks) / len(ranks)
                vs_best = statistics.mean(r["mine"] / r["best_other"] for r in res)
                vs_med = statistics.mean(r["mine"] / r["median"] for r in res)
                by_slot = [statistics.mean(r["rank"] for r in res[s * seeds:(s + 1) * seeds]) for s in range(TEAMS)]
                print(f"   {strat:13} avg rank {statistics.mean(ranks):4.1f} | 1st {win:4.0%} | top3 {top3:4.0%} | "
                      f"vs best opp {vs_best:5.1%} | vs median {vs_med:5.1%} | avg rank by slot "
                      + " ".join(f"{x:.0f}" for x in by_slot))


if __name__ == "__main__":
    main()
