"""Collect dated ranking boards and build historical inputs without outcome leakage."""
import argparse
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re
import shutil
import urllib.request

from .backtest import digest, get_json, totals_for
from .config import ROOT, SLOTS, read_json, write_json
from .strategy_lab import espn_ranks, key, position_fields

CUTOFFS = {2018: "2017-10-16", 2019: "2018-10-15", 2020: "2019-10-21", 2022: "2021-10-18",
           2023: "2022-10-17", 2024: "2023-10-23", 2025: "2024-10-21", 2026: "2025-10-21", 2027: "2026-10-18"}


class Page(HTMLParser):
    """Extract explicit table cells and numbered lists, never execute page scripts."""
    def __init__(self, text):
        super().__init__()
        self.tables, self.lists, self.titles = [], [], []
        self.table = self.row = self.cell = self.ol = self.li = self.title = None
        self.start = 1
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table":
            if self.table is not None:
                raise ValueError("Nested ranking tables need an explicit adapter")
            self.table = []
        if tag == "tr" and self.table is not None:
            self.row = []
        if tag in {"td", "th"} and self.row is not None:
            self.cell = []
        if tag == "ol":
            if self.ol is not None:
                raise ValueError("Nested numbered rankings need an explicit adapter")
            self.ol, self.start = [], int(attrs.get("start", 1))
        if tag == "li" and self.ol is not None:
            self.li = []
        if tag == "title":
            self.title = []

    def handle_data(self, value):
        for field in ("cell", "li", "title"):
            if getattr(self, field) is not None:
                getattr(self, field).append(value)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        if tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
        if tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None
        if tag == "li" and self.li is not None:
            self.ol.append(" ".join("".join(self.li).split()))
            self.li = None
        if tag == "ol" and self.ol is not None:
            self.lists.append((self.start, self.ol))
            self.ol = None
        if tag == "title" and self.title is not None:
            self.titles.append("".join(self.title))
            self.title = None


def dates(text, allow_missing_modified=False):
    result = {}
    for field in ("datePublished", "dateModified"):
        values = sorted(set(re.findall(r'"'+field+r'"\s*:\s*"([^"\\]+)"', text)))
        if not values and field == "dateModified" and allow_missing_modified:
            continue
        if len(values) != 1:
            raise ValueError("Missing or ambiguous article dates")
        # Validate timestamps, not just the first date-shaped substring.
        datetime.fromisoformat(values[0].replace("Z", "+00:00"))
        result[field] = values[0]
    return result


def validate_rows(rows, spec):
    if len(rows) != spec["count"]:
        raise ValueError(f"Expected {spec['count']} published rows, got {len(rows)}")
    if any(type(r.get("rank")) is not int or r["rank"] <= 0 or not key(r.get("name", "")) for r in rows):
        raise ValueError("Missing/invalid rank or player identity")
    if len({key(r["name"]) for r in rows}) != len(rows):
        raise ValueError("Duplicate normalized player identities")
    if not spec.get("allow_ties") and {r["rank"] for r in rows} != set(range(1, len(rows)+1)):
        raise ValueError("Published ranking is incomplete or has duplicate ranks")
    if any(r["rank"] > len(rows) for r in rows):
        raise ValueError("Published rank exceeds board coverage")
    return sorted(rows, key=lambda r: (r["rank"], key(r["name"])))


def parse_html(text, spec):
    page, mode = Page(text), spec["parser"]
    evidence = dates(text, allow_missing_modified=spec["season"] == 2027)
    if not page.titles or not re.search(spec["title_pattern"], page.titles[0], re.I):
        raise ValueError("Unexpected title; possible redirect or wrong season")
    rows = []
    if mode == "table":
        table = page.tables[spec.get("table", 0)]
        header = table[0]
        if header != spec["headers"]:
            raise ValueError("Ranking table columns changed")
        for cells in table[1:]:
            if len(cells) != len(header):
                raise ValueError("Incomplete ranking table row")
            raw = dict(zip(header, cells))
            name = " ".join(raw[k] for k in spec["name_columns"])
            positions = re.findall(r"PG|SG|SF|PF|C", raw.get(spec.get("position_column", "Pos"), ""))
            row = {"rank": int(raw[spec["rank_column"]]), "name": name, "positions": positions}
            forecast = {}
            for column in spec.get("forecast_columns", []):
                number = float(raw[column])
                if not math.isfinite(number) or number < 0:
                    raise ValueError("Invalid published forecast")
                forecast[column] = number
            if forecast:
                row["forecast"] = forecast
            rows.append(row)
    elif mode == "ordered":
        lists = page.lists[spec.get("list_start", 0):]
        if not spec.get("combine_lists"):
            lists = lists[:1]
        for start, items in lists:
            for offset, item in enumerate(items):
                if len(rows) >= spec["count"]:
                    break
                name = re.split(spec["name_split"], item, maxsplit=1)[0].strip()
                if spec.get("trailing_team_position"):
                    name = re.sub(r"\s+[A-Z]{2,3}\s+[GFC](?:/[GFC])?$", "", name)
                rows.append({"rank": start+offset, "name": name, "positions": []})
    else:
        raise ValueError("Unknown HTML adapter")
    return validate_rows(rows, spec), evidence


def parse_pdf(filename, spec):
    import pdfplumber
    with pdfplumber.open(filename) as pdf:
        evidence = {k: pdf.metadata.get(k) for k in ("CreationDate", "ModDate")}
        if any(not re.match(r"^D:\d{8}", value or "") for value in evidence.values()):
            raise ValueError("Missing PDF date evidence")
        evidence = {k: datetime.strptime(value[2:16], "%Y%m%d%H%M%S").isoformat()+value[16:].replace("'", "")
                    for k, value in evidence.items()}
        if spec["parser"] == "espn_pdf":
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
            ranks = espn_ranks(text, spec["count"])
        elif spec["parser"] == "nbc_pdf":
            text = "\n".join(pdf.pages[i].extract_text() or "" for i in spec["pages"]).replace("I ND", "IND")
            ranks = {}
            for rank, name, pos in re.findall(r"(?:^|\s)(\d+)\.\s+(.+?)\s+((?:PG|SG|SF|PF|C|G|F)(?:/(?:PG|SG|SF|PF|C|G|F))*)\s+[A-Z]{2,3}\b", text):
                if int(rank) in ranks:
                    raise ValueError("Duplicate PDF rank")
                ranks[int(rank)] = {"name": name.strip(), "positions": re.findall(r"PG|SG|SF|PF|C", pos)}
        else:
            raise ValueError("Unknown PDF adapter")
    return validate_rows([{"rank": rank, **row} for rank, row in ranks.items()], spec), evidence


def eligibility(spec, evidence, retrieved_at=None):
    cutoff = datetime.fromisoformat(CUTOFFS[spec["season"]]+"T00:00:00-04:00")
    def instant(value):
        # Date-only evidence conservatively means the end of that Eastern day.
        stamp = datetime.fromisoformat(value+"T23:59:59.999999-04:00" if len(value) == 10 else value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("Source timestamp has no timezone")
        return stamp
    values = [instant(v) for v in evidence.values()]
    if not values or any(v >= cutoff for v in values):
        return "diagnostic", "Source was modified on/after the pre-draft cutoff; no clean historical snapshot"
    if min(values).year != spec["season"]-1:
        return "diagnostic", "Publication year does not match the claimed preseason"
    if spec["format"] != "points":
        return "category_only", "Category rankings are excluded from points-board tests"
    if spec["season"] == 2027:
        if not retrieved_at or instant(retrieved_at) >= cutoff:
            return "diagnostic", "Prospective source was not captured before this league's draft cutoff"
        return "prospective", "Captured before this league's draft; no season outcomes exist yet"
    return "preseason", "Publisher/PDF dates precede cutoff; original bytes are not independently timestamped"


def collect(root, manifest):
    root.mkdir(parents=True, exist_ok=True)
    results = []
    for spec in manifest:
        entry = {"source": spec, "retrieved_at": datetime.now(timezone.utc).isoformat()}
        try:
            ext = ".pdf" if spec["parser"].endswith("pdf") else ".html"
            rawfile = root / "raw" / (spec["id"]+ext)
            rawfile.parent.mkdir(parents=True, exist_ok=True)
            if not rawfile.exists():
                cached = Path(spec.get("cache_from", ""))
                if cached.is_file():
                    shutil.copyfile(cached, rawfile)
                else:
                    request = urllib.request.Request(spec["url"], headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(request, timeout=30) as response:
                        if response.geturl().split("?", 1)[0].rstrip("/") != spec["url"].split("?", 1)[0].rstrip("/"):
                            raise ValueError("Source redirected; review its identity before accepting")
                        rawfile.write_bytes(response.read())
            entry["sha256"] = hashlib.sha256(rawfile.read_bytes()).hexdigest()
            capture_file = rawfile.with_suffix(rawfile.suffix+".capture.json")
            capture = read_json(capture_file)
            if capture:
                if capture["url"] != spec["url"] or capture["sha256"] != entry["sha256"]:
                    raise ValueError("Captured bytes/URL changed; preserve the old snapshot and use a new source ID")
                entry["retrieved_at"] = capture["retrieved_at"]
            else:
                write_json(capture_file, {"url": spec["url"], "sha256": entry["sha256"], "retrieved_at": entry["retrieved_at"]})
            rows, evidence = parse_pdf(rawfile, spec) if ext == ".pdf" else parse_html(rawfile.read_text(encoding="utf-8"), spec)
            status, note = eligibility(spec, evidence, entry["retrieved_at"])
            entry.update(status=status, note=note, date_evidence=evidence, rows=rows,
                         full_league_projection=False)
        except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            entry.update(status="unavailable", note=str(exc), rows=[])
        entry["board_sha256"] = digest(entry)
        write_json(root / "boards" / (spec["id"]+".json"), entry)
        results.append({k: v for k, v in entry.items() if k != "rows"} | {"rows": len(entry["rows"])})
        print(json.dumps({"source": spec["id"], "status": entry["status"], "rows": len(entry["rows"]), "note": entry["note"]}), flush=True)
    write_json(root / "catalog.json", results)
    return results


def checked_board(root, board):
    if digest({k: v for k, v in board.items() if k != "board_sha256"}) != board.get("board_sha256"):
        raise ValueError("Normalized board changed after collection")
    spec = board["source"]
    ext = ".pdf" if spec["parser"].endswith("pdf") else ".html"
    rawfile = root / "raw" / (spec["id"]+ext)
    if hashlib.sha256(rawfile.read_bytes()).hexdigest() != board["sha256"]:
        raise ValueError("Ranking source bytes changed after collection")
    if eligibility(spec, board["date_evidence"], board["retrieved_at"])[0] != board["status"]:
        raise ValueError("Ranking source eligibility changed")
    validate_rows(board["rows"], spec)


def resolve_name(name, identities, prior_identities):
    # Prior regular-season NBA statistics disambiguate stale fantasy duplicates
    # without using target-season games, status, teams or positions.
    known = prior_identities.get(key(name), set())
    candidates = known or identities.get(key(name), set())
    return next(iter(candidates)) if len(candidates) == 1 else None


def build(root, history_root, years):
    summaries = []
    for year in years:
        boards = [read_json(file) for file in sorted((root / "boards").glob("*.json"))]
        boards = [b for b in boards if b["source"]["season"] == year and b["status"] == "preseason"]
        if not boards:
            raise ValueError(f"No usable preseason points board for {year}")
        for board in boards:
            checked_board(root, board)
        # Read prior statistics only. This command never fetches target-year outcomes.
        histories = {y: totals_for(y, history_root) for y in (year-2, year-1)}
        def metadata(y):
            return get_json(f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{y}/players?view=players_wl",
                            history_root / "raw" / f"positions-{y}.json", {"x-fantasy-filter": json.dumps({"filterActive": None})})
        prior = {int(p["id"]): p for p in metadata(year-1)}
        identities, prior_identities = {}, {}
        for p in metadata(year):
            identities.setdefault(key(p["fullName"]), set()).add(int(p["id"]))
        for rows in histories.values():
            for pid, p in rows.items():
                prior_identities.setdefault(key(p["name"]), set()).add(pid)
        resolved, unresolved, fallback, excluded = {}, [], [], []
        rank_maps = {}
        for board in boards:
            source_id = board["source"]["id"]
            rank_maps[source_id] = {}
            for row in board["rows"]:
                name = board["source"].get("name_aliases", {}).get(row["name"], row["name"])
                pid = resolve_name(name, identities, prior_identities)
                if pid is None:
                    unresolved.append({"source": source_id, "rank": row["rank"], "name": row["name"],
                                       "reason": "unmatched or ambiguous; no unique prior NBA identity"})
                    continue
                rank_maps[source_id][str(pid)] = row["rank"]
                resolved.setdefault(pid, row)
        universe = set(resolved) | set().union(*(set(rows) for rows in histories.values()))
        players = []
        baseline = next((b["source"]["id"] for b in boards if b["source"]["family"] == "ESPN"), boards[0]["source"]["id"])
        for pid in sorted(universe):
            old = prior.get(pid, {})
            eligible = [SLOTS[s] for s in old.get("eligibleSlots", []) if s in SLOTS]
            primary = SLOTS.get(old.get("defaultPositionId", 0)-1)
            if primary and set(eligible) & {"PG", "SG", "SF", "PF", "C"}:
                positions = {"primary": primary, "eligible": eligible}
            elif pid in resolved and resolved[pid]["positions"]:
                positions = position_fields(resolved[pid]["positions"])
                fallback.append(pid)
            else:
                excluded.append(pid)
                continue
            latest = histories[year-1].get(pid) or histories[year-2].get(pid)
            name = latest["name"] if latest else resolved[pid]["name"]
            players.append({"id": pid, "name": name, "team": "0", **positions, "owner": 0, "slot": "BE", "status": "UNKNOWN",
                            "availability": "FREEAGENT", "adp": None, "auction_value": None, "undroppable": False,
                            "expert_rank": rank_maps[baseline].get(str(pid)),
                            "splits": [{"season": y, "source": 0, "stats": rows[pid]["stats"]} for y, rows in histories.items() if pid in rows]})
        included = {p["id"] for p in players}
        provenance = [{"id": b["source"]["id"], "family": b["source"]["family"], "url": b["source"]["url"],
                       "sha256": b["sha256"], "date_evidence": b["date_evidence"], "basis": b["source"]["basis"],
                       "published_rows": len(b["rows"]), "matched_rows": len(rank_maps[b["source"]["id"]]),
                       "usable_rows": sum(int(pid) in included for pid in rank_maps[b["source"]["id"]])} for b in boards]
        pack = {"season": year, "cutoff": CUTOFFS[year]+"T00:00:00-04:00", "players": players, "sources": provenance,
                "baseline_source": baseline, "ranking_boards": {s: {pid: rank for pid, rank in ranks.items() if int(pid) in included} for s, ranks in rank_maps.items()},
                "unresolved_names": unresolved, "published_position_fallback": fallback, "missing_positions": excluded}
        write_json(root / f"input-{year}.json", pack)
        summaries.append({"season": year, "pool": len(players), "sources": provenance, "unresolved": unresolved,
                          "missing_positions": len(excluded), "position_fallback": len(fallback), "input_sha256": digest(pack)})
        print(json.dumps({"season": year, "pool": len(players), "boards": len(boards), "unresolved": len(unresolved)}), flush=True)
    write_json(root / "inputs-summary.json", summaries)
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("collect", "build"))
    parser.add_argument("--root", type=Path, default=Path("basketball/data/ranking-library"))
    parser.add_argument("--history-root", type=Path, default=Path("basketball/data/backtest"))
    parser.add_argument("--manifest", type=Path, default=ROOT / "ranking_sources.json")
    parser.add_argument("--years", type=int, nargs="+", default=[2018, 2019, 2023, 2024, 2025, 2026])
    args = parser.parse_args()
    if args.action == "collect":
        collect(args.root, read_json(args.manifest))
    else:
        build(args.root, args.history_root, args.years)


if __name__ == "__main__":
    main()
