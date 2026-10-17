"""League configuration, durable local files, and NBA/ESPN identifiers."""
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parent
SLOTS = {0: "PG", 1: "SG", 2: "SF", 3: "PF", 4: "C", 5: "G", 6: "F",
         7: "SG/SF", 8: "G/F", 9: "PF/C", 10: "F/C", 11: "UTIL", 12: "BE", 13: "IR"}
SLOT_IDS = {v: k for k, v in SLOTS.items()}
STATS = {0: "PTS", 1: "BLK", 2: "STL", 3: "AST", 4: "OREB", 5: "DREB", 6: "REB",
         7: "EJ", 8: "FF", 9: "PF", 10: "TF", 11: "TO", 12: "DQ", 13: "FGM", 14: "FGA",
         15: "FTM", 16: "FTA", 17: "3PM", 18: "3PA", 19: "FG%", 20: "FT%", 21: "3PT%",
         22: "AFG%", 23: "FGMI", 24: "FTMI", 25: "3PMI", 35: "A/TO", 37: "DD", 38: "TD",
         39: "QD", 40: "MIN", 41: "GS", 42: "GP"}
INACTIVE = {"OUT", "INJURY_RESERVE", "SUSPENSION"}


def read_json(path, default=None):
    return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else default


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def load(path=None):
    path = Path(path or ROOT / "league.json").resolve()
    cfg = read_json(path)
    if not cfg:
        raise ValueError(f"Missing league configuration: {path}")
    if cfg["format"] not in {"points", "categories", "roto"}:
        raise ValueError("format must be points, categories or roto")
    if cfg["lineup_lock"] not in {"daily", "weekly"}:
        raise ValueError("lineup_lock must be daily or weekly")
    if any(s not in SLOT_IDS or not isinstance(n, int) or n < 0 for s, n in cfg["slots"].items()):
        raise ValueError("Unsupported slots or slot counts")
    if not cfg.get("scoring") and cfg["format"] == "points":
        raise ValueError("Points scoring weights must be configured")
    if set(cfg.get("punts", [])) - set(cfg.get("categories", [])):
        raise ValueError("Punts must be league categories")
    if any(not math.isfinite(float(v)) for v in cfg.get("scoring", {}).values()):
        raise ValueError("Scoring weights must be finite")
    if cfg.get("auto_adds", 0) < 0 or (cfg.get("acquisition_limit") is not None and cfg["acquisition_limit"] < 0):
        raise ValueError("Acquisition limits must be nonnegative or null for unlimited")
    cfg["_path"] = str(path)
    cfg["_data"] = str((path.parent / cfg.get("data_dir", "data")).resolve())
    return cfg


def now(cfg):
    try:
        return datetime.now(ZoneInfo(cfg["timezone"]))
    except ZoneInfoNotFoundError as exc:
        raise ValueError("Install tzdata for IANA timezone support on Windows: python -m pip install tzdata") from exc


def instant(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def active_slots(cfg):
    return [s for s, n in cfg["slots"].items() if s not in {"BE", "IR"} for _ in range(n)]


def roster_size(cfg):
    return sum(n for s, n in cfg["slots"].items() if s != "IR")


def path(cfg, name):
    return Path(cfg["_data"]) / name


def identity(cfg):
    return {k: cfg[k] for k in ("league_id", "team_id", "season")}


def credentials(cfg):
    saved = read_json(path(cfg, "auth.json"), {})
    return {"espn_s2": os.environ.get("ESPN_S2", saved.get("espn_s2", "")),
            "SWID": os.environ.get("ESPN_SWID", saved.get("SWID", ""))}
