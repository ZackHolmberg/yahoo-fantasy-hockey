"""This season's actual fantasy points per player (league 23491 scoring), from the NHL stats API.

manage.py blends them into the preseason projections (Bayesian shrinkage: the preseason FP/G counts as PRIOR_GAMES
games of evidence), so a hot or cold start moves a player's value without overreacting to a dozen games.
Usage: python3 in_season.py   # refresh data/in_season.json (daily_auto.py does this before each Yahoo run)
"""
import json
import re
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

import project  # scoring functions (Yahoo scoring unless LEAGUE=espn)

REPO = Path(__file__).resolve().parent
OUT = REPO / "data/in_season.json"
SEASON = "20262027"
PRIOR_GAMES = 25  # games of evidence the preseason projection is worth


def norm(s):
    return re.sub(r"[^a-z ]", "", unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()).strip()


def get(kind, report):
    q = urllib.parse.urlencode({"limit": -1, "cayenneExp": f"seasonId={SEASON} and gameTypeId=2"})
    req = urllib.request.Request(f"https://api.nhle.com/stats/rest/en/{kind}/{report}?{q}", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return {x["playerId"]: x for x in json.load(r)["data"]}


def refresh():
    summ, rt, fo, goalies = get("skater", "summary"), get("skater", "realtime"), get("skater", "faceoffwins"), get("goalie", "summary")
    out = {}
    for pid, s in summ.items():
        if s["gamesPlayed"]:
            group = "D" if s["positionCode"] == "D" else "F"
            out[f"{norm(s['skaterFullName'])}|{group}"] = {"gp": s["gamesPlayed"], "fp": round(project.skater_season_fp(s, rt.get(pid, {}), fo.get(pid, {})), 1)}
    for g in goalies.values():
        if g["gamesPlayed"]:
            out[f"{norm(g['goalieFullName'])}|G"] = {"gp": g["gamesPlayed"], "fp": round(project.goalie_season_fp(g), 1)}
    OUT.write_text(json.dumps(out))
    return len(out)


def load():
    try:
        return json.loads(OUT.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def blend(fpg, key, actuals):
    """Preseason FP/G shrunk toward this season's actual FP/G by games played."""
    a = actuals.get(key)
    if not a or not fpg:
        return fpg
    return (fpg * PRIOR_GAMES + a["fp"]) / (PRIOR_GAMES + a["gp"])


if __name__ == "__main__":
    print(f"wrote {OUT} ({refresh()} players)")
