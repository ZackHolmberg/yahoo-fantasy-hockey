"""Command-line interface. Reads/previews are default; writes require --execute."""
import argparse
import csv
from datetime import date, timedelta
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time
import urllib.error
from xml.sax.saxutils import escape

from . import drafting, bans
from .config import ROOT, identity, load, now, path, read_json, write_json
from .espn import Client, import_settings, load_snapshot, login, normalize
from .manager import (ledger, lineup_body, matchup_report, reconcile, report,
                      resolve_not_executed, run_lock, send_checked, swap_body, trade_body, trade_response_body)
from .model import Model, totals
from .planner import horizon, moves, trade, trade_ideas


def parser():
    p = argparse.ArgumentParser(description="ESPN fantasy basketball draft and team manager")
    p.add_argument("--config", default=str(ROOT / "league.json"))
    p.add_argument("--snapshot", help="Offline ESPN-normalized snapshot (writes still refresh ESPN)")
    p.add_argument("--fetch", action="store_true", help="Refresh ESPN before analysis")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("login", help="Sign in interactively and save ESPN-only cookies")
    sub.add_parser("fetch", help="Read all league rosters, all players, projections, ADP and NBA schedules")
    settings = sub.add_parser("settings", help="Show verified league rules; optionally refresh API scoring/slots")
    settings.add_argument("--sync", action="store_true")
    imp = sub.add_parser("import", help="Import the read-only basketball_read.js browser export")
    imp.add_argument("file")
    for cmd in ("roster", "report", "matchup", "standings", "trade-ideas", "reconcile"):
        sub.add_parser(cmd)
    resolve = sub.add_parser("resolve-write", help="After checking ESPN, explicitly attest a failed write was not executed")
    resolve.add_argument("index", type=int)
    resolve.add_argument("--not-executed", action="store_true", required=True)
    ranks = sub.add_parser("rankings")
    ranks.add_argument("--limit", type=int, default=200)
    ranks.add_argument("--csv")
    sheet = sub.add_parser("cheatsheet")
    sheet.add_argument("--out", default="BASKETBALL_DRAFT_SHEET.md")
    for cmd in ("lineup", "stream"):
        s = sub.add_parser(cmd)
        s.add_argument("--date")
        s.add_argument("--days", type=int, default=7 if cmd == "stream" else 1)
        s.add_argument("--target-opponent", action="store_true")
    playoffs = sub.add_parser("playoffs")
    playoffs.add_argument("--weeks", nargs="*", help="Week-start ISO dates; otherwise use ESPN playoff period dates")
    t = sub.add_parser("trade")
    t.add_argument("--team", type=int, required=True)
    t.add_argument("--give", nargs="+", required=True)
    t.add_argument("--get", nargs="+", required=True)
    t.add_argument("--propose", action="store_true", help="Build a trade offer rather than only evaluate")
    t.add_argument("--execute", action="store_true")
    respond = sub.add_parser("trade-response")
    respond.add_argument("offer_id")
    response = respond.add_mutually_exclusive_group(required=True)
    response.add_argument("--accept", action="store_true")
    response.add_argument("--decline", action="store_true")
    respond.add_argument("--execute", action="store_true")
    swap = sub.add_parser("swap")
    swap.add_argument("add")
    swap.add_argument("drop", nargs="?")
    swap.add_argument("--bid", type=int)
    swap.add_argument("--execute", action="store_true")
    for cmd in ("apply", "run"):
        s = sub.add_parser(cmd)
        s.add_argument("--execute", action="store_true")
        if cmd == "run":
            s.add_argument("--watch", type=int, metavar="SECONDS", help="Portable foreground scheduler; minimum 60 seconds")
    command = sub.add_parser("command", help="Interpret an owner instruction; preview by default")
    command.add_argument("text")
    command.add_argument("--execute", action="store_true")
    schedule = sub.add_parser("schedule")
    schedule.add_argument("--time", default="10:30")
    schedule.add_argument("--out", default="basketball-task.xml" if sys.platform == "win32" else "basketball-cron.txt")
    schedule.add_argument("--execute", action="store_true", help="Include mutation permission in the scheduled command")
    draft = sub.add_parser("draft")
    ds = draft.add_subparsers(dest="action", required=True)
    best = ds.add_parser("best")
    best.add_argument("--limit", type=int, default=20)
    best.add_argument("--pick", type=int)
    best.add_argument("--slot", type=int)
    ds.add_parser("sync")
    ds.add_parser("reset")
    ds.add_parser("status", help="Read live WebSocket draft state and pending command")
    ds.add_parser("bans", help="List persistent player and NBA team draft bans")
    for action in ("ban", "unban"):
        rule = ds.add_parser(action, help="Add/remove a hard draft exclusion")
        rule.add_argument("kind", choices=("player", "team"))
        rule.add_argument("target", help="Player name/ESPN ID or NBA team name/abbreviation/ID")
    available = ds.add_parser("availability", help="Verify current NBA profile, roster and injury sources")
    available.add_argument("player")
    available.add_argument("--refresh", action="store_true")
    risk = ds.add_parser("review-risk", help="Explicitly accept a currently verified injury concern; never override blocked/unknown")
    risk.add_argument("player")
    risk.add_argument("--reason", required=True)
    risk.add_argument("--hours", type=float, default=2)
    ds.add_parser("reconcile", help="Recover confirmation of an uncertain API draft command")
    resolve_draft = ds.add_parser("resolve", help="After checking ESPN, attest the uncertain draft command did not execute")
    resolve_draft.add_argument("--not-executed", action="store_true", required=True)
    watch = ds.add_parser("watch", help="Refresh ESPN picks and recommendations until interrupted")
    watch.add_argument("--seconds", type=int, default=15, help="Browser polling interval; API mode listens continuously")
    watch.add_argument("--slot", type=int)
    watch.add_argument("--execute", action="store_true", help="Pick on your turns using the live draft API")
    watch.add_argument("--transport", choices=("api", "browser"), default="api")
    for action in ("mine", "taken", "undo", "paste"):
        s = ds.add_parser(action)
        s.add_argument("names", nargs="*")
        s.add_argument("--team", type=int)
        s.add_argument("--cost", type=int, default=0)
    a = ds.add_parser("auction")
    a.add_argument("player")
    a.add_argument("--current-bid", type=int, default=0)
    for action in ("pick", "queue", "bid"):
        s = ds.add_parser(action)
        s.add_argument("player")
        s.add_argument("--amount", type=int)
        s.add_argument("--execute", action="store_true")
        s.add_argument("--transport", choices=("api", "browser"), default="api")
    return p


def public_body(body):
    return {k: v for k, v in body.items() if k != "memberId"}


def apply(cfg, args):
    with run_lock(cfg):
        snap = load_snapshot(cfg, args.snapshot, fresh=args.execute or args.fetch)
        model = Model(cfg, snap)
        plan = report(model)
        bodies, results = [], []
        if plan["lineup"]:
            body = lineup_body(model, plan["lineup"])
            bodies.append(public_body(body))
            if args.execute:
                result = send_checked(model, body)
                results.append(result)
                if not result["verified"]:
                    return {"plan": plan, "requests": bodies, "results": results, "stopped": "Lineup not yet verified"}
                model = Model(cfg, load_snapshot(cfg))
                plan = report(model)
        if plan["auto_move"]:
            move = plan["auto_move"]
            body = swap_body(model, move["add"], move["drop"])
            bodies.append(public_body(body))
            if args.execute:
                results.append(send_checked(model, body, auto=True))
        result = {"preview": not args.execute, "plan": plan, "requests": bodies, "results": results}
        if args.execute:
            write_json(path(cfg, "last_run.json"), result)
        return result


def schedule_file(cfg, args):
    try:
        hour, minute = map(int, args.time.split(":"))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError()
    except ValueError as exc:
        raise ValueError("Schedule time must be HH:MM") from exc
    # Generate a self-contained absolute command; no shell interpolation of user text.
    command = [sys.executable, "-m", "basketball", "--config", cfg["_path"], "--fetch", "run"]
    if args.execute:
        command.append("--execute")
    cwd = str(ROOT.parent)
    if sys.platform == "win32":
        text = f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers><CalendarTrigger><StartBoundary>{now(cfg).date().isoformat()}T{hour:02}:{minute:02}:00</StartBoundary><Enabled>true</Enabled><ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger></Triggers>
  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><StartWhenAvailable>true</StartWhenAvailable><ExecutionTimeLimit>PT20M</ExecutionTimeLimit></Settings>
  <Actions><Exec><Command>{escape(sys.executable)}</Command><Arguments>{escape(subprocess.list2cmdline(command[1:]))}</Arguments><WorkingDirectory>{escape(cwd)}</WorkingDirectory></Exec></Actions>
</Task>
'''
        Path(args.out).write_text(text, encoding="utf-16")
        install = subprocess.list2cmdline(["schtasks", "/Create", "/TN", f"ESPN Basketball {cfg['league_id']}", "/XML", str(Path(args.out).resolve())])
    else:
        text = f"{minute} {hour} * * * cd {shlex.quote(cwd)} && {shlex.join(command)} >> {shlex.quote(str(path(cfg, 'scheduler.log')))} 2>&1\n"
        Path(args.out).write_text(text, encoding="utf-8")
        install = "Add the generated line to your user crontab"
    return {"file": str(Path(args.out).resolve()), "install": install,
            "timezone": "Uses the scheduler host's local timezone; set it to " + cfg["timezone"], "installed": False}


def playoff_report(model, weeks):
    if not weeks:
        weeks = model.cfg.get("playoff_weeks", [])
    if not weeks:
        settings = model.snapshot.get("settings", {}).get("scheduleSettings", {})
        regular = settings.get("matchupPeriodCount", model.cfg.get("regular_season_matchups", 18))
        periods = settings.get("matchupPeriods", {})
        playoff_ids = {int(x) for k, ids in periods.items() if int(k) > regular for x in ids}
        dates = sorted({g["date"] for rows in model.snapshot.get("games", {}).values() for g in rows if g.get("period") in playoff_ids})
        if dates:
            first, last = date.fromisoformat(dates[0]), date.fromisoformat(dates[-1])
            weeks = [(first + timedelta(days=i)).isoformat() for i in range(0, (last - first).days + 1, 7)]
    if not weeks:
        raise ValueError("No authoritative playoff dates in snapshot; use playoffs --weeks YYYY-MM-DD ...")
    rows = []
    for p in model.players:
        schedule = model.snapshot.get("games", {}).get(p["team"], [])
        counts = [sum(w <= g["date"] < (date.fromisoformat(w) + timedelta(days=7)).isoformat() and not g.get("cancelled") for g in schedule) for w in weeks]
        rows.append({"id": p["id"], "name": p["name"], "owner": p["owner"], "games": counts,
                     "value": round(sum(counts) * p["value"], 2)})
    return {"weeks": weeks, "players": sorted(rows, key=lambda r: -r["value"]),
            "roster_lineups": {w: horizon(model, date.fromisoformat(w), 7) for w in weeks}}


def standings(model):
    teams = model.snapshot["teams"]
    if model.cfg["format"] != "roto":
        return [{"team": t["id"], "name": t["name"], "record": t.get("record", {})} for t in teams]
    totals_by = {t["id"]: t.get("totals") for t in teams}
    if any(v is None for v in totals_by.values()):
        raise ValueError("Roto standings require season totals for every team in the snapshot")
    out = []
    for t in teams:
        scores = {}
        for c in model.cfg["categories"]:
            val = totals_by[t["id"]].get(c, 0)
            other = [totals_by[q["id"]].get(c, 0) for q in teams]
            direction = -1 if c in model.cfg.get("lower_is_better", []) else 1
            scores[c] = 1 + sum(v * direction < val * direction for v in other) + (sum(v == val for v in other) - 1) / 2
        out.append({"team": t["id"], "name": t["name"], "categories": scores, "points": sum(scores.values())})
    return sorted(out, key=lambda t: -t["points"])


def run(args):
    cfg = load(args.config)
    if args.command == "draft" and args.action in {"bans", "ban", "unban"}:
        if args.action == "bans":
            return bans.listing(cfg)
        kind = "players" if args.kind == "player" else "teams"
        if args.action == "unban":
            return bans.remove(cfg, kind, args.target)
        if kind == "teams":
            entry = bans.team(cfg, args.target)
        elif args.target.isdigit() and int(args.target) > 0:
            entry = {"id": int(args.target), "name": args.target}
        else:
            p = Model(cfg, load_snapshot(cfg, args.snapshot, fresh=args.fetch)).find(args.target)
            entry = {"id": p["id"], "name": p["name"]}
        return bans.edit(cfg, kind, entry)
    if args.command == "draft" and args.action in {"availability", "review-risk"}:
        from . import availability
        player = {"id": int(args.player), "name": args.player, "status": "ACTIVE"} if args.player.isdigit() else Model(cfg, load_snapshot(cfg, args.snapshot, fresh=args.fetch)).find(args.player)
        return availability.check(cfg, player, args.refresh) if args.action == "availability" else availability.review_risk(cfg, player, args.reason, args.hours)
    if args.command == "login":
        return login(cfg)
    if args.command == "settings":
        if args.sync:
            import_settings(cfg, Client(cfg).settings())
        return {k: v for k, v in cfg.items() if not k.startswith("_")}
    if args.command == "schedule":
        return schedule_file(cfg, args)
    if args.command == "draft" and (args.action in {"status", "reconcile", "resolve"} or
            getattr(args, "transport", None) == "api" and (args.action == "watch" or args.execute)):
        if args.action == "watch" and args.seconds < 1:
            raise ValueError("Draft watch interval must be at least 1 second")
        from .draft_api import run as run_draft_api
        return run_draft_api(cfg, args)
    if args.command == "import":
        raw = read_json(args.file)
        if int(raw["league"].get("id", 0)) != cfg["league_id"]:
            raise ValueError("Browser export is for a different league")
        snap = normalize(cfg, raw["league"], raw["players"], raw["season"])
        write_json(path(cfg, "snapshot.json"), snap)
        return {"imported": len(snap["players"]), **identity(cfg)}
    if args.command in {"apply", "run"}:
        if args.command == "run" and args.watch is not None:
            if args.watch < 60:
                raise ValueError("Watch interval must be at least 60 seconds")
            args.fetch = True
            while True:
                result = apply(cfg, args)
                print(json.dumps(result, ensure_ascii=False), flush=True)
                time.sleep(args.watch)
        return apply(cfg, args)
    snap = load_snapshot(cfg, args.snapshot, fresh=args.fetch or args.command == "fetch")
    model = Model(cfg, snap)
    day = date.fromisoformat(args.date) if getattr(args, "date", None) else now(cfg).date()
    if args.command == "fetch":
        return {"players": len(model.players), "teams": len(snap["teams"]), "fetched_at": snap["fetched_at"]}
    if args.command == "roster":
        return model.roster()
    if args.command == "report":
        return report(model, day)
    if args.command == "matchup":
        return matchup_report(model, day)
    if args.command == "standings":
        return standings(model)
    if args.command == "trade":
        if args.execute and not args.propose:
            raise ValueError("Use trade --propose --execute to send an offer")
        if args.propose:
            with run_lock(cfg):
                if args.execute:
                    model = Model(cfg, Client(cfg).fetch())
                body = trade_body(model, args.give, args.get, args.team)
                return send_checked(model, body) if args.execute else {"preview": True, "request": public_body(body), "evaluation": trade(model, args.give, args.get, args.team)}
        return trade(model, args.give, args.get, args.team)
    if args.command == "trade-response":
        with run_lock(cfg):
            if args.execute:
                model = Model(cfg, Client(cfg).fetch())
            body = trade_response_body(model, args.offer_id, args.accept)
            return send_checked(model, body) if args.execute else {"preview": True, "request": public_body(body)}
    if args.command == "trade-ideas":
        return trade_ideas(model)
    if args.command == "reconcile":
        if not args.fetch:
            raise ValueError("Reconcile requires --fetch so an old snapshot cannot confirm a write")
        with run_lock(cfg):
            return reconcile(cfg, snap)
    if args.command == "resolve-write":
        if not args.fetch:
            raise ValueError("resolve-write requires --fetch and an explicit --not-executed attestation")
        with run_lock(cfg):
            return resolve_not_executed(cfg, Client(cfg).fetch(), args.index)
    if args.command == "swap":
        with run_lock(cfg):
            # Refresh inside the same lock as mutation, rather than relying on a read made before it.
            if args.execute:
                model = Model(cfg, Client(cfg).fetch())
            body = swap_body(model, args.add, args.drop, approved=True, bid=args.bid)
            return send_checked(model, body) if args.execute else {"preview": True, "request": public_body(body)}
    if args.command == "command":
        from .commands import interpret
        with run_lock(cfg):
            if args.execute:
                model = Model(cfg, Client(cfg).fetch())
            result = interpret(model, args.text)
            if "body" not in result:
                return result
            return send_checked(model, result["body"]) if args.execute else {"preview": True, "request": public_body(result["body"])}
    if args.command in {"lineup", "stream"}:
        if not 1 <= args.days <= 31:
            raise ValueError("Plan horizon must be 1 to 31 days")
        weights = matchup_report(model, day).get("target_weights") if args.target_opponent else None
        if args.command == "lineup":
            return horizon(model, day, args.days, at=now(cfg) if day == now(cfg).date() else None, weights=weights)
        from .planner import acquisitions_used
        used = acquisitions_used(model)
        remaining = max(0, cfg["acquisition_limit"] - used) if used is not None and cfg.get("acquisition_limit") is not None else None
        return {"acquisition_limit": cfg.get("acquisition_limit"), "remaining_acquisitions": remaining,
                "candidates": [] if remaining == 0 else moves(model, day, args.days, streaming=True, weights=weights, at=now(cfg) if day == now(cfg).date() else None),
                "note": "Single-move recommendations; recompute after each acquisition. Waiver clearance and lineup congestion are included."}
    if args.command == "playoffs":
        return playoff_report(model, args.weeks)
    if args.command in {"rankings", "cheatsheet"}:
        policy = bans.listing(cfg)
        rows = [r for r in drafting.rankings(model) if not bans.reason(cfg, model.by_id[r["id"]], policy=policy)]
        rows = rows[:getattr(args, "limit", cfg["teams"] * 12)]
        if args.command == "rankings":
            if args.csv and rows:
                with open(args.csv, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
            return rows
        lines = [f"# {cfg['name']} — basketball draft sheet", "", f"{cfg['teams']} teams; {cfg['format']}; source {snap['fetched_at']}", "",
                 "| Rank | Player | Positions | FP/G | VOR | ADP | Status |", "|---|---|---|---|---|---|---|"]
        lines += [f"| {i} | {r['name']} | {', '.join(s for s in r['eligible'] if s not in {'BE', 'IR'})} | {r['fpg']} | {r['vor']} | {r['adp'] or ''} | {r['status']} |" for i, r in enumerate(rows, 1)]
        Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {"file": str(Path(args.out).resolve()), "players": len(rows)}
    if args.command == "draft":
        if args.action == "watch":
            if args.seconds < 10:
                raise ValueError("Draft polling must be at least 10 seconds")
            last = None
            while True:
                with run_lock(cfg):
                    latest = Client(cfg).settings()
                    snap["draft"] = latest.get("draftDetail", {})
                    order = latest.get("settings", {}).get("draftSettings", {}).get("pickOrder", [])
                    if not args.slot and cfg["team_id"] in order:
                        cfg["draft"]["slot"] = order.index(cfg["team_id"]) + 1
                    model = Model(cfg, snap)
                    drafting.sync(model)
                    current = bans.board(model, slot=args.slot)
                    if current["pick"] != last:
                        print(json.dumps(current, ensure_ascii=False), flush=True)
                        last = current["pick"]
                    slot = args.slot or cfg["draft"].get("slot")
                    if args.execute:
                        if cfg["draft"]["type"] != "snake" or not slot:
                            raise ValueError("Automatic watch needs a snake draft and a known slot; auction bids are explicit")
                        if current["pick"] in drafting.snake_picks(cfg["teams"], slot, sum(n for s, n in cfg["slots"].items() if s != "IR")):
                            from .browser import draft_action
                            from .availability import verified_choice
                            candidate, checks = verified_choice(model)
                            print(json.dumps({"availability_checks": checks}), flush=True)
                            print(json.dumps(draft_action(model, "pick", candidate["id"], execute=True)), flush=True)
                time.sleep(args.seconds)
        with run_lock(cfg):
            if args.action == "best":
                return {**bans.board(model, args.limit, args.pick, args.slot), "availability_checked": False,
                        "availability_instruction": "Use draft availability PLAYER; every executed pick, queue or bid verifies current sources."}
            if args.action == "sync":
                return drafting.sync(model)
            if args.action == "reset":
                write_json(path(cfg, "draft.json"), {"picks": []})
                return {"reset": True}
            if args.action in {"mine", "taken", "undo", "paste"}:
                names = args.names or ([sys.stdin.read()] if args.action == "paste" else [])
                return drafting.record(model, names, cfg["team_id"] if args.action == "mine" else args.team,
                                       args.cost, args.action == "undo", args.action == "paste")
            if args.action == "auction":
                return bans.auction(model, args.player, args.current_bid)
            if args.transport == "api":
                from .draft_api import preview
                return preview(model, args.action, args.player, args.amount)
            from .browser import draft_action
            return draft_action(model, args.action, args.player, args.execute, args.amount)
    raise ValueError("Unknown command")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    args = parser().parse_args()
    try:
        result = run(args)
    except (ValueError, OSError, KeyError, urllib.error.URLError) as exc:
        print(f"basketball: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except KeyboardInterrupt:
        raise SystemExit(130)
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
