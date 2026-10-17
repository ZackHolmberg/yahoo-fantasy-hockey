"""Focused live-draft contract and recovery tests; never mutate an ESPN league."""
import base64
import copy
import hashlib
import socket
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

from basketball.cli import parser, run
from basketball.config import STATS, load, path, read_json, write_json
from basketball.draft_api import Decoder, Room, confirmed, preview, reconcile
from basketball.model import Model
from basketball.espn import player as normalize_player
from test_basketball import athlete, snapshot


MEMBER = "{11111111-2222-3333-4444-555555555555}"
AUTH = {"espn_s2": "test-secret-cookie", "SWID": MEMBER}


def init_frame(league=2141453434, team=18, state=1, picks=(), queue=()):
    """Hand-encoded subset of ESPN's Java INIT format, independent of SCHEMAS.

    Rules, slot/position arrays and optional lists are absent in this fixture.
    Signed league IDs on the wire can exceed 2**31; our configured ID does not.
    """
    b = bytearray()

    def ints(*values):
        b.extend(struct.pack(">" + "i" * len(values), *values))

    ints(1, 1, league, team)  # DraftInit v1
    ints(1, 1, league, 1, 0, 0, state)  # DraftLeague v1, no date
    ints(0, 0, 0, 0)  # no block/rules, zero positions/slots
    ints(len(picks))
    for pick, player, owner in picks:
        ints(1, 3, league, owner, pick, player, 0, 0, 0)  # DraftPick v3
        b.extend(b"\0")  # keeper flag
        ints(0, 0)
    ints(1)  # one DraftTeam v2
    ints(1, 2, league, team, 1, 0, 200, 0, 0)
    ints(0)  # no DraftList (pre-draft rankings, not the live queue)
    ints(1, 1, league, team, len(queue))  # NominationList v1 = live queue
    for ordinal, player in enumerate(queue):
        ints(1, 1, league, team, ordinal + 1, player, 1)
    return "INIT " + base64.b64encode(b).decode() + "\n"


class FakeSocket:
    def __init__(self, frames, outcome="pick"):
        self.frames = list(frames)
        self.sent = []
        self.outcome = outcome
        self.closed = False

    def settimeout(self, timeout):
        pass

    def recv(self):
        return self.frames.pop(0) if self.frames else ""

    def send(self, command):
        self.sent.append(command)
        if command.startswith("PING "):
            self.frames.append("PONG " + command[5:])
        elif command.startswith("SELECT "):
            self.frames.append("SELECTED 18 " + command.split()[1] + " 0\n" if self.outcome == "pick" else "")
        elif command.startswith("DRAFT_LIST"):
            self.frames.append(command)
        elif command.startswith("BID "):
            _, player, bid = command.split()
            self.frames.append(f"BID 18 {player} {bid} 60000 50000\nBID 2 {player} {int(bid)+1} 60000 49000\n")

    def close(self):
        self.closed = True


class DraftApiTests(unittest.TestCase):
    def setUp(self):
        availability_gate = patch("basketball.draft_api.availability.require", return_value={"allowed": True, "status": "clear", "fixture": True})
        availability_gate.start()
        self.addCleanup(availability_gate.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = load()
        self.cfg.update(_data=self.tmp.name, teams=2, slots={"PG": 1, "SG": 1, "UTIL": 1, "BE": 1})
        self.cfg["scoring"] = {"PTS": 1}
        self.players = [athlete(1, ("PG", "SG"), ppg=35), athlete(2, ("PG",)), athlete(3, ("SG",))]
        self.model = Model(self.cfg, snapshot(self.players))
        self.raw = {"id": self.cfg["league_id"], "seasonId": 2027, "gameId": 3, "scoringPeriodId": 0,
                    "teams": [{"id": 18, "owners": [MEMBER]}, {"id": 2, "owners": []}],
                    "settings": {"size": 2, "scoringSettings": {"scoringType": "H2H_POINTS", "scoringItems": [{"statId": 0, "points": 1}]},
                                 "rosterSettings": {"lineupSlotCounts": {"0": 1, "1": 1, "11": 1, "12": 1}}}, "players": []}
        ids = {v: k for k, v in STATS.items()}
        slots = {"PG": 0, "SG": 1, "G": 5, "UTIL": 11, "BE": 12, "IR": 13}
        for player in self.players:
            self.raw["players"].append({"id": player["id"], "player": {"id": player["id"], "fullName": player["name"],
                "defaultPositionId": 1, "proTeamId": player["id"], "eligibleSlots": [slots[s] for s in player["eligible"]],
                "stats": [{"seasonId": 2027, "statSourceId": 1, "stats": {str(ids[k]): v for k, v in player["splits"][0]["stats"].items()}}]}})

    def room(self, state=1, queue=(), outcome="pick", turn=18, clock=60000):
        room = Room(self.cfg)
        room.raw = copy.deepcopy(self.raw)
        room.socket = FakeSocket([init_frame(state=state, queue=queue), f"SELECTING {turn} {clock}\nCLOCK 1 {clock} {turn}\n"], outcome)
        room.wait_for(lambda: room.init is not None)
        return room

    def test_init_decodes_picks_queue_and_signed_fields(self):
        frame = init_frame(picks=[(1, 123, 2)], queue=[456, 789])
        init = Decoder(frame.split()[1]).decode()
        self.assertEqual(init["league"]["draftPicks"][0]["playerId"], 123)
        self.assertEqual(init["league"]["draftTeams"][0]["amountLeft"], 200)
        self.assertEqual([p["playerId"] for p in init["nominationList"]["nominationListPlayers"]], [456, 789])

    def test_init_rejects_version_truncation_and_trailing_data(self):
        data = base64.b64decode(init_frame().split()[1])
        for bad in (data[:4] + struct.pack(">i", 99) + data[8:], data[:-1], data + b"x"):
            with self.assertRaises(ValueError):
                Decoder(base64.b64encode(bad)).decode()

    def test_socket_rejects_wrong_identity(self):
        with self.assertRaisesRegex(ValueError, "different league"):
            self.room().consume(init_frame(team=2))

    def test_pick_is_sent_once_and_only_server_ack_records_success(self):
        room = self.room()
        result = room.execute("pick", 1)
        self.assertTrue(result["verified"])
        self.assertEqual(room.socket.sent[-1], "SELECT 1\n")
        self.assertIsNone(read_json(path(self.cfg, "draft-write.json")))
        self.assertEqual(len(read_json(path(self.cfg, "draft-receipts.json"))), 1)
        self.assertEqual(read_json(path(self.cfg, "draft.json"))["picks"][0]["player"], 1)
        with self.assertRaises(ValueError):
            room.execute("pick", 1)
        self.assertEqual(room.socket.sent.count("SELECT 1\n"), 1)

    def test_turn_paused_expired_and_unknown_phase_send_no_selection(self):
        for kwargs in ({"turn": 2}, {"state": 3}, {"clock": 24999}, {"state": 2}):
            with self.subTest(kwargs=kwargs):
                room = self.room(**kwargs)
                with self.assertRaises(ValueError):
                    room.execute("pick", 1)
                self.assertFalse(any(x.startswith("SELECT ") for x in room.socket.sent))
        room = self.room()
        room.receive()
        room.consume("CLOCK 2 60000 18 1 1")
        with self.assertRaisesRegex(ValueError, "turn"):
            room.check(self.model, "pick", self.model.find(1), None)

    def test_queue_preserves_existing_order_and_requires_echo(self):
        room = self.room(state=3, queue=[3])
        self.assertTrue(room.execute("queue", 1)["verified"])
        self.assertIn("DRAFT_LIST 3 1\n", room.socket.sent)
        self.assertTrue(room.execute("queue", 1)["already_present"])
        self.assertEqual(room.socket.sent.count("DRAFT_LIST 3 1\n"), 1)

    def test_disconnect_leaves_durable_intent_and_blocks_another_write(self):
        room = self.room(outcome="disconnect")
        with self.assertRaisesRegex(ValueError, "closed"):
            room.execute("pick", 1)
        self.assertEqual(read_json(path(self.cfg, "draft-write.json"))["player"], 1)
        with self.assertRaisesRegex(ValueError, "Unconfirmed"):
            self.room().execute("pick", 2)
        recovered = self.room()
        recovered.consume(init_frame(picks=[(1, 1, 18)]))
        self.assertIsNone(reconcile(recovered))
        self.assertEqual(len(read_json(path(self.cfg, "draft-receipts.json"))), 1)

    def test_ack_from_another_team_does_not_confirm_pick(self):
        room = self.room()
        intent = {"action": "pick", "player": 1, "pick": 1}
        room.consume("SELECTED 2 1 0")
        self.assertFalse(confirmed(room, intent))

    def test_unknown_intent_identity_stops_reconciliation(self):
        write_json(path(self.cfg, "draft-write.json"), {"league_id": 999})
        with self.assertRaisesRegex(ValueError, "different league"):
            reconcile(self.room())

    def test_recovery_does_not_duplicate_receipt_after_local_crash(self):
        room = self.room()
        room.execute("pick", 1)
        receipt = read_json(path(self.cfg, "draft-receipts.json"))[0]
        write_json(path(self.cfg, "draft-write.json"), {k: v for k, v in receipt.items() if k != "verified_at"})
        reconcile(room)
        self.assertEqual(len(read_json(path(self.cfg, "draft-receipts.json"))), 1)

    def test_live_rules_override_stale_config_without_persisting_config(self):
        room = self.room()
        room.raw["settings"]["scoringSettings"]["scoringItems"][0]["points"] = 3
        original = copy.deepcopy(self.cfg)
        model = room.model()
        self.assertEqual(model.cfg["scoring"], {"PTS": 3})
        self.assertEqual(self.cfg, original)

    def test_completed_watch_saves_roster_without_postdraft_http_read(self):
        from basketball.draft_api import run as api_run
        room = self.room(state=2)
        room.consume(init_frame(state=2, picks=[(1, 1, 18)]))
        args = parser().parse_args(["draft", "watch", "--execute"])
        with patch("basketball.draft_api.Room", return_value=room), patch.object(Room, "__enter__", return_value=room):
            result = api_run(self.cfg, args)
        self.assertEqual(result["state"], "complete")
        self.assertEqual(result["roster"][0]["name"], "Player 1")
        self.assertEqual(read_json(path(self.cfg, "draft-result.json")), result)

    def test_api_can_pick_legal_expert_rookie_without_a_projection(self):
        room = self.room()
        room.raw['players'][0]['player']['stats'] = []
        self.assertFalse(room.model().by_id[1]['ranked'])
        self.assertTrue(room.execute('pick', 1)['verified'])
        self.assertEqual(room.socket.sent.count('SELECT 1\n'), 1)

    def test_expert_watch_verifies_selected_board_order_before_api_submission(self):
        from basketball.draft_api import run as api_run
        room = self.room()
        args = parser().parse_args(['draft', 'watch', '--strategy', 'expert', '--source', 'rotowire', '--execute'])
        original_execute = room.execute
        original_receive = room.receive
        sent = room.socket.sent
        def execute(*args):
            result = original_execute(*args)
            room.state = 2
            return result
        candidates = [{'id': 2, 'name': 'Player 2'}, {'id': 1, 'name': 'Player 1'}]
        with patch('basketball.draft_api.Room', return_value=room), patch.object(Room, '__enter__', return_value=room), \
                patch('basketball.draft_api.expert_board', return_value={'players': candidates}) as expert, \
                patch('basketball.availability.check', side_effect=[{'allowed': False}, {'allowed': True}]) as check, \
                patch.object(room, 'execute', side_effect=execute), \
                patch.object(room, 'receive', side_effect=lambda timeout=1: False if room.state == 2 else original_receive(timeout)), patch('builtins.print'):
            result = api_run(self.cfg, args)
        self.assertEqual([call.args[1]['id'] for call in check.call_args_list], [2, 1])
        self.assertEqual(sent.count('SELECT 1\n'), 1)
        self.assertFalse(any(s.startswith('SELECT 2') for s in sent))
        self.assertEqual(result['state'], 'complete')
        self.assertTrue(all(call.args[1] == 'rotowire' for call in expert.call_args_list))

    def test_draft_security_accepts_plain_text_and_json_string(self):
        from io import BytesIO
        from basketball.espn import Client
        for data in (b"test-token", b'"test-token"'):
            with patch("basketball.espn.urllib.request.urlopen", return_value=BytesIO(data)):
                self.assertEqual(Client(self.cfg).request("https://lm-api-reads.fantasy.espn.com/token", text=True), "test-token")

    def test_live_init_replaces_stale_manual_picks(self):
        write_json(path(self.cfg, "draft.json"), {"picks": [{"player": 1, "team": 18, "pick": 1}]})
        room = self.room()
        room.model()
        self.assertEqual(read_json(path(self.cfg, "draft.json"))["picks"], [])

    def test_future_keeper_does_not_shift_current_pick(self):
        room = self.room()
        room.consume(init_frame(picks=[(7, 3, 2)]))
        room.consume("SELECTED 18 1 0")
        self.assertEqual(room.picks[-1]["pickNumber"], 1)
        self.assertEqual(room.next_pick(), 2)

    def test_live_schedule_ignores_minus_one_and_retains_skipped_picks(self):
        room = self.room()
        room.consume(init_frame(picks=[(1, 123, 2), (2, 0, 18), (3, -1, 2), (4, -1, 18)]))
        self.assertEqual(len(room.picks), 2)
        self.assertEqual(room.next_pick(), 3)
        self.assertEqual(room.selecting, 2)
        room.consume("CLOCK")
        self.assertEqual(room.seconds_left(), 0)
        room.consume("SELECTED 2 0 0")
        self.assertEqual(room.next_pick(), 4)

    def test_draft_init_external_id_year_is_normalized(self):
        raw = copy.deepcopy(self.raw["players"][0])
        raw["player"]["stats"][0].pop("seasonId")
        raw["player"]["stats"][0]["externalId"] = "2027"
        self.assertEqual(normalize_player(raw)["splits"][0]["season"], 2027)

    def test_bid_ack_survives_immediate_outbid_in_same_frame(self):
        room = self.room()
        room.receive()
        room.draft_type = 4
        self.cfg["draft"]["type"] = "auction"
        room.consume("BID 2 1 1 60000 50000")
        self.assertTrue(room.execute("bid", 1, 2)["verified"])
        self.assertEqual(room.high_team, 2)
        self.assertIn("BID 1 2\n", room.socket.sent)

    def test_auction_eligibility_and_reserve_guard(self):
        room = self.room()
        room.receive()
        room.draft_type = 4
        self.cfg["draft"]["type"] = "auction"
        room.consume("BID 2 1 2 60000 50000")
        for player, bid in ((1, 2), (1, 201), (2, 3)):
            with self.assertRaises(ValueError):
                room.check(room.model(), "bid", self.model.find(player), bid)

    def test_auth_handshake_uses_espn_security_and_never_browser(self):
        from unittest.mock import Mock
        client = Mock()
        client.draft_init.return_value = self.raw
        client.request.return_value = "secret-token"
        client.league = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/2027/segments/0/leagues/2141453434"
        socket = FakeSocket([init_frame()])
        with patch("basketball.draft_api.credentials", return_value=AUTH), patch("websocket.create_connection", return_value=socket) as connect:
            with Room(self.cfg, client) as room:
                self.assertEqual(room.status()["state"], "live")
            url = connect.call_args.args[0]
            self.assertTrue(url.startswith("wss://fantasydraft.espn.com/game-3/league-2141453434/JOIN?"))
            self.assertIn("&4=" + MEMBER + "&5=3:2141453434:18:", url)
            self.assertIn("secret-token", url)
            self.assertNotIn(AUTH["espn_s2"], url)
            self.assertIn(AUTH["espn_s2"], connect.call_args.kwargs["cookie"])
            self.assertTrue(client.request.call_args.args[0].endswith("/teams/18/draftSecurity"))
            self.assertTrue(socket.closed)

    def test_connection_errors_do_not_leak_secret_join_url(self):
        from unittest.mock import Mock
        client = Mock()
        client.draft_init.return_value = self.raw
        client.request.return_value = "secret-token"
        client.league = "https://lm-api-reads.fantasy.espn.com/league"
        with patch("basketball.draft_api.credentials", return_value=AUTH), patch("websocket.create_connection", side_effect=OSError("JOIN?token=secret-token")):
            with self.assertRaisesRegex(ValueError, "connection failed") as caught:
                with Room(self.cfg, client):
                    pass
            self.assertNotIn("secret-token", str(caught.exception))

    def test_preview_and_api_cli_routing_do_not_need_offline_cache(self):
        self.assertEqual(preview(self.model, "pick", 1)["transport"], "api")
        for command in (["draft", "status"], ["draft", "pick", "1", "--execute"], ["draft", "watch", "--execute"]):
            args = parser().parse_args(command)
            with patch("basketball.draft_api.run", return_value={"transport": "api"}) as api, patch("basketball.cli.load_snapshot", side_effect=AssertionError("offline cache")):
                self.assertEqual(run(args)["transport"], "api")
                api.assert_called_once()
        self.assertEqual(parser().parse_args(["draft", "pick", "1", "--transport", "browser"]).transport, "browser")

    def test_pick_round_trip_over_real_local_websocket(self):
        """Exercise websocket-client framing and Room together over TCP."""
        from websocket import create_connection
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(5)
        self.addCleanup(listener.close)
        commands, failures = [], []

        def server():
            try:
                with listener.accept()[0] as connection:
                    connection.settimeout(5)
                    request = b""
                    while b"\r\n\r\n" not in request:
                        request += connection.recv(4096)
                    key = next(line.split(b":", 1)[1].strip() for line in request.split(b"\r\n") if line.lower().startswith(b"sec-websocket-key:"))
                    accept = base64.b64encode(hashlib.sha1(key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest())
                    connection.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: " + accept + b"\r\n\r\n")

                    def emit(text):
                        data = text.encode()
                        header = bytes([0x81, len(data)]) if len(data) < 126 else b"\x81\x7e" + struct.pack(">H", len(data))
                        connection.sendall(header + data)

                    def exact(count):
                        data = b""
                        while len(data) < count:
                            part = connection.recv(count - len(data))
                            if not part:
                                raise RuntimeError("Client disconnected")
                            data += part
                        return data

                    emit(init_frame())
                    emit("SELECTING 18 60000\nCLOCK 1 60000 18\n")
                    while True:
                        opcode, size = exact(2)
                        if opcode & 15 == 8:
                            break
                        masked, length = bool(size & 128), size & 127
                        if length == 126:
                            length = struct.unpack(">H", exact(2))[0]
                        mask = exact(4) if masked else b"\0\0\0\0"
                        payload = exact(length)
                        command = bytes(value ^ mask[i % 4] for i, value in enumerate(payload)).decode()
                        commands.append(command)
                        if command.startswith("PING "):
                            emit("PONG " + command[5:])
                        elif command == "SELECT 1\n":
                            emit("SELECTED 18 1 0\n")
                        else:
                            raise AssertionError(command)
            except Exception as exc:
                failures.append(exc)

        worker = threading.Thread(target=server, daemon=True)
        worker.start()
        room = Room(self.cfg)
        room.raw = self.raw
        try:
            room.socket = create_connection(f"ws://127.0.0.1:{listener.getsockname()[1]}", timeout=5)
            room.wait_for(lambda: room.init is not None)
            self.assertTrue(room.execute("pick", 1)["verified"])
        finally:
            room.close()
            worker.join(6)
        self.assertFalse(worker.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(commands.count("SELECT 1\n"), 1)


if __name__ == "__main__":
    unittest.main()
