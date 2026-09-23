"""Pull regular-season skater and goalie stats from the public NHL stats API."""
import json
import sys
from pathlib import Path

import requests

BASE = "https://api.nhle.com/stats/rest/en"
REPORTS = {
    "skater": ["summary", "realtime", "faceoffwins"],
    "goalie": ["summary"],
}
OUT = Path("data/raw")


def fetch(kind, report, season):
    rows, start = [], 0
    while True:
        r = requests.get(
            f"{BASE}/{kind}/{report}",
            params={
                "limit": 100,
                "start": start,
                "sort": '[{"property":"playerId","direction":"ASC"}]',
                "cayenneExp": f"seasonId={season} and gameTypeId=2",
            },
            timeout=30,
        )
        r.raise_for_status()
        page = r.json()["data"]
        rows += page
        if len(page) < 100:
            return rows
        start += 100


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for season in sys.argv[1:] or ["20242025", "20252026"]:
        for kind, reports in REPORTS.items():
            for report in reports:
                rows = fetch(kind, report, season)
                (OUT / f"{kind}_{report}_{season}.json").write_text(json.dumps(rows))
                print(kind, report, season, len(rows))
