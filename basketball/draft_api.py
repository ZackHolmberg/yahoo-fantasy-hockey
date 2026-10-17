"""ESPN live draft protocol: authenticated WebSocket commands and server receipts.

Wire contract observed in ESPN's basketball draft.js, build
449ae61ae2f5-1.520 (2026-10-16). See docs/BASKETBALL.md for the source.
No browser, guessed REST writes, automatic retries, or credential logging.
"""
import base64
import copy
import json
import secrets
import struct
import time
from urllib.parse import urlencode
from uuid import UUID

from .config import credentials, identity, now, path, read_json, write_json
from .drafting import auction, board
from .espn import Client, import_settings, normalize
from .manager import run_lock
from .model import Model
from . import availability


# Versioned, big-endian Java storables in INIT. Optional objects begin with a
# presence int and a version int; arrays begin with a count int.
SCHEMAS = {
    "init": (1, "leagueId:i teamId:i league:league draftList:list nominationList:nominations"),
    "league": (1, "leagueId:i draftType:i universeId:i draftDate:date draftState:i draftBlock:block draftRules:rules draftPositions:[position] draftSlots:[slot] draftPicks:[pick] draftTeams:[team]"),
    "block": (1, "leagueId:i state:i expirationTime:date nominationTeamIndex:i upForBidPlayerId:i highBidTeamId:i highBidSlotId:i highBidAmount:i"),
    "rules": (2, "leagueId:i initialPickTime:i minimumPickTime:i nominationTime:i selectionTime:i breakSchedule:break autodraftProtection:protection pauseTime:i nominationDelay:i minimumBid:i maximumBid:i minimumHighBidMultiplier:d maximumHighBidMultiplier:d minimumCurrentBidMultiplier:d maximumCurrentBidMultiplier:d defaultBalance:i isRosterCompletionRequired:b benchSlotCategoryId:i injurySlotCategoryId:i invalidSlotCategoryId:i isCensorDefault:b isChatCaptureWanted:b scoringSettings:scoring isFirstTierProtected:b"),
    "break": (1, "leagueId:i interval:i intervalType:i"),
    "protection": (1, "leagueId:i cutoff:i cutoffType:i"),
    "scoring": (1, "leagueId:i scoringType:i scoringCategories:[category]"),
    "category": (3, "leagueId:i statId:i scoringValue:d isTeamStat:b"),
    "position": (1, "leagueId:i positionId:i positionMax:i"),
    "slot": (1, "leagueId:i slotId:i slotCategoryId:i positions:[slotPosition]"),
    "slotPosition": (1, "leagueId:i slotCategoryId:i positionId:i"),
    "pick": (3, "leagueId:i teamId:i pickNumber:i playerId:i slotId:i bidAmount:i nominatingTeamId:i isKeeper:b autodraftTypeId:i selectorUserProfileId:i"),
    "team": (2, "leagueId:i teamId:i draftPosition:i autodraftTypeId:i amountLeft:i owners:[owner] draftRosterItems:[roster]"),
    "owner": (1, "leagueId:i teamId:i userProfileId:i isLM:b isOnline:b isCensorEnabled:b"),
    "roster": (1, "leagueId:i teamId:i slotId:i playerId:i isKeeper:b"),
    "list": (1, "leagueId:i teamId:i isCustom:b draftListPlayers:[listPlayer]"),
    "listPlayer": (1, "leagueId:i teamId:i playerId:i draftValue:i ordinalRank:i"),
    "nominations": (1, "leagueId:i teamId:i nominationListPlayers:[nomination]"),
    "nomination": (1, "leagueId:i teamId:i nominationId:i playerId:i initialBid:i"),
}


class Decoder:
    def __init__(self, encoded):
        try:
            self.data = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("Invalid ESPN draft INIT encoding") from exc
        self.offset = 0

    def read(self, kind):
        if kind in {"i", "b", "d", "long"}:
            fmt = {"i": ">i", "b": ">B", "d": ">d", "long": ">q"}[kind]
            size = struct.calcsize(fmt)
            if self.offset + size > len(self.data):
                raise ValueError("Truncated ESPN draft INIT")
            value = struct.unpack_from(fmt, self.data, self.offset)[0]
            self.offset += size
            if kind == "b":
                if value not in (0, 1):
                    raise ValueError("Invalid ESPN draft boolean")
                return bool(value)
            return value
        if kind == "date":
            return self.read("long") if self.read("i") else None
        if kind.startswith("["):
            size = self.read("i")
            if not 0 <= size <= 10000:
                raise ValueError("Invalid ESPN draft array size")
            return [self.read(kind[1:-1]) for _ in range(size)]
        present = self.read("i")
        if present == 0:
            return None
        if present != 1:
            raise ValueError("Invalid ESPN draft object marker")
        version, fields = SCHEMAS[kind]
        if self.read("i") != version:
            raise ValueError(f"ESPN changed the {kind} draft protocol; execution stopped")
        return {name: self.read(typ) for name, typ in (f.split(":") for f in fields.split())}

    def decode(self):
        value = self.read("init")
        if self.offset != len(self.data) or not value or not value.get("league"):
            raise ValueError("Unexpected ESPN draft INIT structure")
        return value


class Room:
    """One authenticated connection. Commands are sent once, then acknowledged."""
    def __init__(self, cfg, client=None):
        self.cfg = cfg
        self.client = client or Client(cfg)
        self.socket = None
        self.init = None
        self.raw = None
        self.state = None
        self.draft_type = None
        self.picks = []
        self.queue = []
        self.selecting = None
        self.phase = None
        self.deadline = None
        self.block_player = None
        self.high_team = None
        self.high_bid = 0
        self.last_ping = time.monotonic()
        self.bid_receipts = set()

    def __enter__(self):
        auth = credentials(self.cfg)
        if not auth["espn_s2"] or not auth["SWID"]:
            raise ValueError("Run `python -m basketball login` before connecting to the draft API")
        try:
            member = "{" + str(UUID(auth["SWID"].strip("{}"))).upper() + "}"
        except ValueError as exc:
            raise ValueError("ESPN_SWID is not a valid ESPN member identifier") from exc
        self.raw = self.client.draft_init()
        normalize(self.cfg, self.raw, self.raw.get("players", []), {})  # identity and team
        team = next(t for t in self.raw["teams"] if t["id"] == self.cfg["team_id"])
        if member.casefold() not in {str(x).casefold() for x in team.get("owners", [])}:
            raise ValueError("Authenticated ESPN member does not own the configured draft team")
        token = self.client.request(self.client.league + f"/teams/{self.cfg['team_id']}/draftSecurity", text=True)
        if not isinstance(token, str) or not token or any(c.isspace() for c in token):
            raise ValueError("ESPN did not return a valid draft security token")
        security = f"3:{self.cfg['league_id']}:{self.cfg['team_id']}:{member}:{token}"
        query = urlencode({"1": 3, "2": self.cfg["league_id"], "3": self.cfg["team_id"],
                           "4": member, "5": security, "6": "false", "7": "false",
                           "8": "KONA", "nocache": secrets.randbelow(1000000)}, safe=":{}")
        url = f"wss://fantasydraft.espn.com/game-3/league-{self.cfg['league_id']}/JOIN?{query}"
        try:
            from websocket import create_connection
        except ImportError as exc:
            raise ValueError("Install requirements-basketball.txt for the draft WebSocket API") from exc
        try:
            self.socket = create_connection(url, origin="https://fantasy.espn.com", timeout=5,
                                            cookie=f"espn_s2={auth['espn_s2']}; SWID={auth['SWID']}",
                                            header={"User-Agent": "Mozilla/5.0"})
        except Exception as exc:
            self.close()
            # Library errors may contain the authenticated JOIN URL.
            code = getattr(exc, "status_code", None)
            detail = f" (HTTP {code})" if isinstance(code, int) else ""
            raise ValueError(f"ESPN draft API connection failed{detail}; check login and draft availability") from None
        try:
            self.wait_for(lambda: self.init is not None, 10)
        except Exception:
            self.close()
            raise
        return self

    def close(self):
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
            self.socket = None

    def __exit__(self, *args):
        self.close()

    def send(self, command):
        try:
            self.socket.send(command + "\n")
        except Exception:
            raise ValueError("Draft API send failed; reconcile before another attempt") from None

    def receive(self, timeout=1):
        if time.monotonic() - self.last_ping >= 10:
            self.send("PING basketball")
            self.last_ping = time.monotonic()
        self.socket.settimeout(timeout)
        try:
            frame = self.socket.recv()
        except TimeoutError:
            return False
        except Exception as exc:
            # websocket-client's timeout is not a builtin TimeoutError.
            if type(exc).__name__ == "WebSocketTimeoutException":
                return False
            raise ValueError("ESPN draft API disconnected; reconnect and reconcile") from None
        if not frame:
            raise ValueError("ESPN closed the draft API connection")
        if isinstance(frame, bytes):
            frame = frame.decode("utf-8")
        for line in frame.splitlines():
            self.consume(line)
        return True

    def wait_for(self, predicate, seconds=8):
        until = time.monotonic() + seconds
        while not predicate():
            left = until - time.monotonic()
            if left <= 0:
                raise ValueError("ESPN draft acknowledgement timed out; reconcile before retrying")
            self.receive(min(1, left))

    def consume(self, line):
        parts = line.strip().split()
        if not parts:
            return
        name, fields = parts[0], parts[1:]
        if name == "ERROR":
            # Do not log arbitrary server text, which can contain account data.
            raise ValueError("ESPN rejected a draft command; inspect the room before retrying")
        if name == "INIT":
            init = Decoder(fields[0]).decode()
            league = init["league"]
            if (init["leagueId"], init["teamId"], league["leagueId"]) != (self.cfg["league_id"], self.cfg["team_id"], self.cfg["league_id"]):
                raise ValueError("Draft socket returned a different league or team")
            self.init, self.state, self.draft_type = init, league["draftState"], league["draftType"]
            # The socket sends the entire pick schedule; -1 means unselected.
            # Zero is a skipped pick and still occupies its overall number.
            self.picks = [p for p in league["draftPicks"] if p and p["playerId"] >= 0]
            self.queue = [p["playerId"] for p in (init.get("nominationList") or {}).get("nominationListPlayers", [])]
            self.selecting = next((p["teamId"] for p in sorted(league["draftPicks"], key=lambda p: p["pickNumber"])
                                   if p["playerId"] == -1), None) if self.draft_type == 1 else None
            self.phase = self.deadline = None
            block = league.get("draftBlock") or {}
            self.block_player, self.high_team, self.high_bid = block.get("upForBidPlayerId"), block.get("highBidTeamId"), block.get("highBidAmount", 0)
        elif name == "STATE":
            self.state = int(fields[0])
            self.deadline = None
        elif name in {"SELECTING", "NOMINATION"}:
            self.selecting = int(fields[0])
            self.deadline = None  # require a live CLOCK after the turn changed
            self.block_player = self.high_team = None
            self.high_bid = 0
        elif name == "CLOCK":
            phase = int(fields[0]) if fields else -1
            millis = int(fields[1]) if len(fields) > 1 else -1
            self.phase = phase
            if len(fields) > 2 and phase in {1, 6}:
                self.selecting = int(fields[2])
            if len(fields) > 3 and phase == 2:
                self.block_player = int(fields[3])
            self.deadline = time.monotonic() + millis / 1000 if millis >= 0 else None
        elif name in {"SELECTED", "SOLD"}:
            team, player, slot = map(int, fields[:3])
            if player > 0 and any(p["playerId"] == player for p in self.picks):
                raise ValueError("Duplicate draft selection event; reconnect to establish state")
            self.picks.append({"teamId": team, "playerId": player, "slotId": slot,
                               "pickNumber": self.next_pick(),
                               "bidAmount": int(fields[3]) if name == "SOLD" else 0})
            self.selecting = self.deadline = None
        elif name == "BID":
            self.high_team, self.block_player, self.high_bid, _, millis = map(int, fields[:5])
            self.bid_receipts.add((self.high_team, self.block_player, self.high_bid))
            self.phase = 2
            self.deadline = time.monotonic() + millis / 1000
        elif name == "DRAFT_LIST":
            self.queue = [int(x) for x in fields]
        elif name == "PONG":
            self.barrier = fields[0] if fields else None
        elif name in {"RESET", "UNDONE", "ADJUSTED", "SLOT_CHANGED"}:
            raise ValueError("Draft history changed; reconnect to obtain a new authoritative INIT")
        elif name == "LEFT" and int(fields[0]) == self.cfg["team_id"]:
            raise ValueError("Your draft connection left the room; reconnect before acting")

    def seconds_left(self):
        return max(0, self.deadline - time.monotonic()) if self.deadline else 0

    def refresh(self):
        marker = secrets.token_hex(8)
        self.barrier = None
        self.send("PING " + marker)
        self.wait_for(lambda: self.barrier == marker, 5)

    def next_pick(self):
        occupied = {p["pickNumber"] for p in self.picks}
        return next(n for n in range(1, len(occupied) + 2) if n not in occupied)

    def status(self):
        return {**identity(self.cfg), "transport": "api", "state": {0: "before", 1: "live", 2: "complete", 3: "paused"}.get(self.state, "unknown"),
                "type": {1: "snake", 4: "auction", 5: "linear"}.get(self.draft_type, "unsupported"),
                "selecting_team": self.selecting, "seconds_left": round(self.seconds_left(), 1),
                "picks": [{k: p[k] for k in ("teamId", "playerId", "pickNumber", "bidAmount")} for p in self.picks],
                "queue": self.queue, "pending": reconcile(self)}

    def model(self):
        raw = copy.deepcopy(self.raw)
        raw["draftDetail"] = {"picks": [{**p, "overallPickNumber": p["pickNumber"]} for p in self.picks],
                              "drafted": self.state == 2, "inProgress": self.state in (1, 3)}
        cfg = import_settings(copy.deepcopy(self.cfg), raw, persist=False)
        snap = normalize(cfg, raw, raw.get("players", []), {})
        by = {p["id"]: p for p in snap["players"]}
        for pick in self.picks:
            if pick["playerId"] in by:
                by[pick["playerId"]]["owner"] = pick["teamId"]
        # Live INIT replaces manual tracking; stale local picks must not influence
        # legality, turn detection, auction spending, or recommendations.
        write_json(path(self.cfg, "draft.json"), {**identity(self.cfg), "picks": [
            {"player": p["playerId"], "team": p["teamId"], "pick": p["pickNumber"], "cost": p["bidAmount"], "source": "espn"}
            for p in self.picks if p["playerId"] > 0]})
        return Model(cfg, snap)

    def check(self, model, action, player, bid):
        if self.init is None or self.state not in (0, 1, 3):
            raise ValueError("Draft is not available for commands")
        if player["id"] in {p["playerId"] for p in self.picks}:
            raise ValueError("Player has already been drafted")
        if player["id"] not in {p["id"] for p in board(model, len(model.players))["players"]}:
            raise ValueError("Player cannot fit the remaining draft roster")
        if action == "queue":
            if self.draft_type != 1:
                raise ValueError("API queue currently supports snake drafts only")
            return
        if self.state != 1 or self.seconds_left() < 25:
            raise ValueError("Draft must be live with at least 25 seconds on the clock")
        if action == "pick":
            if self.draft_type != 1 or self.phase not in (1, 6) or self.selecting != self.cfg["team_id"]:
                raise ValueError("Live API does not confirm your snake draft turn")
        elif action == "bid":
            if self.draft_type != 4 or self.phase != 2 or self.block_player != player["id"] or self.high_team == self.cfg["team_id"]:
                raise ValueError("Live API does not confirm this player's auction bidding window")
            quote = auction(model, player["id"], self.high_bid)
            minimum = model.cfg["draft"].get("minimum_bid", 1)
            if not isinstance(bid, int) or bid < self.high_bid + minimum or bid > quote["maximum_bid"]:
                raise ValueError("Bid must exceed the live bid and remain within the model's maximum")
        else:
            raise ValueError("Unsupported draft API action")

    def execute(self, action, name, bid=None):
        reconcile(self)
        if read_json(path(self.cfg, "draft-write.json")):
            raise ValueError("Unconfirmed draft command exists; use draft status/reconcile before retrying")
        # Drain frames queued during model computation; a PONG barrier proves
        # that our view includes all messages preceding the server's response.
        self.refresh()
        model = self.model()
        player = model.find(name)
        evidence = availability.require(self.cfg, player)
        # Public-source reads can consume clock time or overlap another pick.
        self.refresh()
        model = self.model()
        player = model.find(name)
        if "fantasy_state" in evidence and evidence["fantasy_state"] != {k: player.get(k) for k in ("status", "active", "team")}:
            raise ValueError("Player status changed during availability verification; refresh before drafting")
        self.check(model, action, player, bid)
        if action == "queue" and player["id"] in self.queue:
            return {"verified": True, "action": action, "id": player["id"], "already_present": True, "transport": "api"}
        if action == "queue":
            command = "DRAFT_LIST " + " ".join(map(str, self.queue + [player["id"]]))
        else:
            command = f"SELECT {player['id']}" if action == "pick" else f"BID {player['id']} {bid}"
        intent = {**identity(self.cfg), "action": action, "player": player["id"], "bid": bid,
                  "pick": self.next_pick(),
                  "at": now(self.cfg).isoformat()}
        intent["availability"] = evidence
        write_json(path(self.cfg, "draft-write.json"), intent)
        self.send(command)
        self.wait_for(lambda: confirmed(self, intent))
        reconcile(self)
        self.model()
        return {"verified": True, "action": action, "player": player["name"], "id": player["id"], "bid": bid, "transport": "api"}


def confirmed(room, intent):
    if intent["action"] == "queue":
        return intent["player"] in room.queue
    if intent["action"] == "bid" and ((room.cfg["team_id"], intent["player"], intent["bid"]) in room.bid_receipts or
            (room.high_team, room.block_player, room.high_bid) == (room.cfg["team_id"], intent["player"], intent["bid"])):
        return True
    return any(p["teamId"] == room.cfg["team_id"] and p["playerId"] == intent["player"]
               and (intent["action"] == "bid" or p["pickNumber"] == intent["pick"])
               and (intent["action"] != "bid" or p["bidAmount"] == intent["bid"]) for p in room.picks)


def reconcile(room):
    filename = path(room.cfg, "draft-write.json")
    intent = read_json(filename)
    if intent:
        if any(intent.get(k) != v for k, v in identity(room.cfg).items()):
            raise ValueError("Draft write journal belongs to a different league/team/season")
        if confirmed(room, intent):
            receipts = read_json(path(room.cfg, "draft-receipts.json"), [])
            if not any(all(receipt.get(k) == v for k, v in intent.items()) for receipt in receipts):
                receipts.append({**intent, "verified_at": now(room.cfg).isoformat()})
                write_json(path(room.cfg, "draft-receipts.json"), receipts)
            write_json(filename, None)
            return None
    return intent


def preview(model, action, name, bid=None):
    player = model.find(name)
    if action not in {"pick", "queue", "bid"}:
        raise ValueError("Unsupported draft API action")
    if player["id"] not in {p["id"] for p in board(model, len(model.players))["players"]}:
        raise ValueError("Player cannot fit the remaining draft roster")
    if action == "bid":
        quote = auction(model, player["id"], (bid or 1) - 1)
        if not isinstance(bid, int) or not 1 <= bid <= quote["maximum_bid"]:
            raise ValueError("Bid is missing or exceeds the model's maximum")
    return {"preview": True, "transport": "api", "action": action, "player": player["name"], "id": player["id"], "bid": bid,
            "availability_checked": False,
            "requirements": "Current availability verification, authenticated API INIT, live turn/bidding window, legal roster, >=25 seconds, server acknowledgement"}


def run(cfg, args):
    with run_lock(cfg), Room(cfg) as room:
        room.refresh()
        if args.action in {"status", "reconcile", "resolve"}:
            if args.action == "resolve":
                intent = reconcile(room)
                if intent:
                    receipts = read_json(path(cfg, "draft-receipts.json"), [])
                    receipts.append({**intent, "resolution": "owner_attested_not_executed", "resolved_at": now(cfg).isoformat()})
                    write_json(path(cfg, "draft-receipts.json"), receipts)
                    write_json(path(cfg, "draft-write.json"), None)
            return room.status()
        if args.action != "watch":
            return room.execute(args.action, args.player, args.amount)
        if args.execute and room.draft_type != 1:
            raise ValueError("Automatic API drafting supports snake drafts only; auction bids are explicit")
        last = None
        while room.state != 2:
            if len(room.picks) != last:
                current = board(room.model(), current=room.next_pick(), slot=args.slot)
                print(json.dumps({**room.status(), "recommendations": current}, ensure_ascii=False), flush=True)
                last = len(room.picks)
            if args.execute and room.state == 1 and room.selecting == cfg["team_id"] and room.seconds_left() >= 25:
                candidate, checks = availability.verified_choice(room.model())
                print(json.dumps({"availability_checks": checks}, ensure_ascii=False), flush=True)
                print(json.dumps(room.execute("pick", candidate["id"]), ensure_ascii=False), flush=True)
            room.receive(1)
        model = room.model()
        result = room.status()
        # ESPN deletes custom mock leagues immediately after completion. Keep
        # names/projections with the server result while the pool is available.
        result["roster"] = [{"id": p["playerId"], "name": model.by_id[p["playerId"]]["name"],
                             "eligible": model.by_id[p["playerId"]]["eligible"],
                             "fpg": round(model.by_id[p["playerId"]]["fpg"], 2), "pick": p["pickNumber"]}
                            for p in room.picks if p["teamId"] == cfg["team_id"] and p["playerId"] > 0]
        write_json(path(cfg, "draft-result.json"), result)
        return result
