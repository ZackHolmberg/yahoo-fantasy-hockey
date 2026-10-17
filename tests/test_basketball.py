"""Focused basketball backend tests; no ESPN login, network, or live mutations."""
import copy
from datetime import date, datetime, timedelta, timezone
import itertools
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from basketball.config import load, path, read_json, write_json
from basketball.drafting import auction, board, rankings, record, snake_picks, survival, sync
from basketball.espn import Client, import_settings, load_snapshot, normalize, player
from basketball.manager import complete_lineup, ledger, reconcile, report, send_checked, swap_body, trade_body, trade_response_body, verify_body
from basketball.model import Model, projection, totals
from basketball.planner import assign, horizon, legal_roster, lineup, moves, trade


def athlete(pid, positions=("PG",), owner=0, slot="BE", ppg=20, team=None, status="ACTIVE"):
    eligible = list(positions) + ["UTIL", "BE", "IR"]
    if set(positions) & {"PG", "SG"}:
        eligible.append("G")
    if set(positions) & {"SF", "PF"}:
        eligible.append("F")
    return {"id": pid, "name": f"Player {pid}", "team": str(team or pid), "primary": positions[0],
            "eligible": eligible, "owner": owner, "slot": slot, "status": status,
            "undroppable": False, "availability": "ONTEAM" if owner else "FREEAGENT", "adp": pid,
            "splits": [{"season": 2027, "source": 1, "stats": {"GP": 70, "PTS": ppg * 70,
                       "FGM": 5 * 70, "FGA": 10 * 70, "FTM": 2 * 70, "FTA": 3 * 70,
                       "REB": 4 * 70, "AST": 3 * 70, "STL": 70, "BLK": 35, "TO": 2 * 70, "3PM": 70}}]}


def snapshot(players):
    games = {p["team"]: [{"id": int(p["team"]) * 100 + i, "date": f"2026-10-{19+i:02}",
                          "start": f"2026-10-{19+i:02}T23:00:00+00:00", "period": i + 1, "cancelled": False} for i in range(7)] for p in players}
    return {"league_id": 2141453434, "team_id": 18, "season": 2027, "source": "fixture",
            "fetched_at": "2026-10-19T10:00:00-04:00", "period": 1, "transaction_period": 1,
            "matchup_period": 1, "players": players, "games": games,
            "teams": [{"id": 18, "name": "Mine", "roster": [p["id"] for p in players if p["owner"] == 18], "acquisitions": 0},
                      {"id": 2, "name": "Theirs", "roster": [p["id"] for p in players if p["owner"] == 2], "acquisitions": 0}],
            "draft": {}, "matchups": [], "settings": {}, "pending": []}


class BasketballTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = load()
        self.cfg.update(_data=self.tmp.name, teams=2, slots={"PG": 1, "SG": 1, "UTIL": 1, "BE": 1, "IR": 1})
        self.cfg["scoring"] = {"PTS": 1}
        self.at = datetime(2026, 10, 19, 14, tzinfo=timezone.utc)
        patcher = patch("basketball.manager.now", return_value=self.at)
        patcher.start()
        self.addCleanup(patcher.stop)

    def model(self, players):
        return Model(self.cfg, snapshot(players))

    def test_actual_league_rules(self):
        cfg = load()
        self.assertEqual(cfg["league_id"], 2141453434)
        self.assertEqual(sum(v for k, v in cfg["slots"].items() if k != "IR"), 12)
        self.assertEqual(cfg["scoring"]["TO"], -2)
        self.assertEqual(cfg["position_limits"], {"C": 4})

    def test_matching_reassigns_flexible_guard(self):
        players = [{"id": 1, "eligible": ["PG", "SG"], "value": 100}, {"id": 2, "eligible": ["PG"], "value": 90}]
        self.assertEqual(assign(players, ["PG", "SG"]), {1: "SG", 2: "PG"})

    def test_matching_matches_exhaustive_optimum(self):
        rng = random.Random(81)
        for _ in range(15):
            slots = ["PG", "SG", "UTIL"]
            ps = [{"id": i, "eligible": [s for s in slots if rng.random() < 0.7], "value": rng.randint(-5, 30)} for i in range(5)]
            actual = assign(ps, slots)
            best = (0, float("-inf"))
            for choices in itertools.product([None] + ps, repeat=3):
                filled = [p["id"] for p in choices if p]
                if len(filled) != len(set(filled)) or any(p and slot not in p["eligible"] for p, slot in zip(choices, slots)):
                    continue
                best = max(best, (len(filled), sum(p["value"] for p in choices if p)))
            self.assertEqual((len(actual), sum(ps[pid]["value"] for pid in actual)), best)

    def test_current_stats_update_preseason_prior(self):
        p = athlete(1, ppg=20)
        p["splits"].append({"season": 2027, "source": 0, "stats": {"GP": 20, "PTS": 800}})
        actual = projection(p, self.cfg, snapshot([p]))
        self.assertEqual(actual["per_game"]["PTS"], 30)
        self.assertEqual(actual["projection_source"], "current_plus_espn_projection")

    def test_unranked_player_is_not_valued_or_auto_added(self):
        p = athlete(1)
        p["splits"] = []
        model = self.model([p, athlete(2, owner=18)])
        self.assertFalse(model.by_id[1]["ranked"])
        self.assertEqual(moves(model, date(2026, 10, 19)), [])

    def test_percentage_is_attempt_weighted(self):
        ps = [{"id": 1, "remaining_games": 1, "per_game": {"FGM": 1, "FGA": 1}},
              {"id": 2, "remaining_games": 1, "per_game": {"FGM": 1, "FGA": 9}}]
        self.assertEqual(totals(ps)["FG%"], 0.2)

    def test_categories_turnovers_and_punts(self):
        self.cfg.update(format="categories", categories=["PTS", "TO"], punts=["PTS"])
        a, b = athlete(1), athlete(2)
        b["splits"][0]["stats"]["TO"] = 700
        model = self.model([a, b])
        self.assertGreater(model.by_id[1]["value"], model.by_id[2]["value"])
        self.assertEqual(model.compare({"TO": 1}, {"TO": 2})["TO"]["winner"], "ours")

    def test_lineup_keeps_started_player_and_locked_bench(self):
        a, b, c = athlete(1, owner=18, slot="PG", ppg=1), athlete(2, owner=18, slot="BE", ppg=100), athlete(3, ("SG",), owner=18, slot="SG")
        model = self.model([a, b, c])
        model.snapshot["games"]["1"][0]["start"] = "2026-10-19T12:00:00+00:00"
        model.snapshot["games"]["2"][0]["start"] = "2026-10-19T12:00:00+00:00"
        plan = lineup(model, "2026-10-19", at=self.at)
        self.assertEqual(plan[1], "PG")
        self.assertNotIn(2, plan)

    def test_nonplaying_players_fill_slots_instead_of_overflowing_bench(self):
        ps = [athlete(1, owner=18, slot="PG"), athlete(2, ("SG",), owner=18, slot="SG"),
              athlete(3, owner=18, slot="UTIL"), athlete(4, owner=18, slot="BE")]
        model = self.model(ps)
        model.snapshot["games"] = {p["team"]: [] for p in ps}
        plan = complete_lineup(model, "2026-10-19", self.at, model.roster())
        self.assertEqual(sum(s == "BE" for s in plan.values()), 1)

    def test_position_maximum(self):
        self.cfg["position_limits"] = {"C": 1}
        self.assertFalse(legal_roster([athlete(1, ("C",)), athlete(2, ("C",))], self.cfg))

    def test_games_cap_and_missing_usage(self):
        self.cfg["games_caps"] = {"ALL": 2}
        model = self.model([athlete(1, owner=18, slot="PG")])
        with self.assertRaisesRegex(ValueError, "games_used"):
            horizon(model, date(2026, 10, 19), 7)
        model.snapshot["games_used"] = {"ALL": 1}
        self.assertEqual(sum(horizon(model, date(2026, 10, 19), 7)["games"].values()), 1)

    def test_ir_moves_only_with_site_eligibility(self):
        a = athlete(1, owner=18, slot="PG", status="OUT")
        b = athlete(2, owner=18, slot="BE", status="OUT")
        b["eligible"].remove("IR")
        plan = report(self.model([a, b]), date(2026, 10, 19), at=self.at)
        self.assertEqual([c["player"] for c in plan["lineup"] if c["to"] == "IR"], [1])

    def test_acquisition_limit_and_protected_drop(self):
        model = self.model([athlete(1, owner=18), athlete(2)])
        self.cfg["protected"] = [1]
        with self.assertRaisesRegex(ValueError, "protected"):
            swap_body(model, 2, 1)
        model.snapshot["teams"][0]["acquisitions"] = 4
        with self.assertRaisesRegex(ValueError, "limit reached"):
            swap_body(model, 2, 1, approved=True)

    def test_unknown_acquisition_count_disables_auto(self):
        model = self.model([athlete(1, owner=18, ppg=1), athlete(2, ppg=100)])
        model.snapshot["teams"][0]["acquisitions"] = None
        result = report(model, date(2026, 10, 19), at=self.at)
        self.assertIsNone(result["auto_move"])

    def test_waiver_claim_and_faab_budget(self):
        a = athlete(2)
        a["availability"] = "WAIVERS"
        model = self.model([athlete(1, owner=18), a])
        self.cfg.update(waiver_system="faab", faab_budget=100)
        self.assertEqual(swap_body(model, 2, 1, bid=20)["bidAmount"], 20)
        with self.assertRaisesRegex(ValueError, "budget"):
            swap_body(model, 2, 1, bid=101)

    def test_waiver_delay_preserves_old_player_until_clearance(self):
        a, b = athlete(1, owner=18, ppg=10), athlete(2, ppg=20)
        b["availability"] = "WAIVERS"
        self.cfg["slots"] = {"PG": 1, "BE": 0}
        model = self.model([a, b])
        rows = moves(model, date(2026, 10, 19), days=2, streaming=True)
        self.assertEqual(rows[0]["gain"], 10)

    def test_draft_sync_and_idempotency(self):
        model = self.model([athlete(1), athlete(2)])
        model.snapshot["draft"] = {"picks": [{"playerId": 1, "teamId": 18, "overallPickNumber": 1}]}
        sync(model)
        sync(model)
        self.assertEqual(len(read_json(path(self.cfg, "draft.json"))["picks"]), 1)
        self.assertNotIn(1, [p["id"] for p in board(model)["players"]])

    def test_draft_paste_can_be_reclassified_as_mine(self):
        model = self.model([athlete(1)])
        record(model, ["Player 1"], paste=True)
        record(model, [1], team=18)
        self.assertEqual(board(model)["remaining_roster_spots"], 3)

    def test_snake_order_and_conditional_adp(self):
        self.assertEqual(snake_picks(16, 3, 3), [3, 30, 35])
        self.assertGreater(survival(40, 10, 20, 10), survival(40, 10, 50, 10))
        self.assertIsNone(survival(None, 10, 20, 10))

    def test_auction_reserves_cash_for_remaining_slots(self):
        model = self.model([athlete(i, ("PG", "SG"), ppg=30 - i) for i in range(1, 10)])
        self.cfg["draft"]["budget"] = 10
        record(model, [1], team=18, cost=7)
        quote = auction(model, 2)
        self.assertLessEqual(quote["maximum_bid"], 1)

    def test_trade_roster_capacity(self):
        model = self.model([athlete(1, owner=18), athlete(2, owner=2), athlete(3, owner=2)])
        self.cfg["slots"] = {"PG": 1}
        with self.assertRaisesRegex(ValueError, "roster"):
            trade(model, [1], [2, 3], 2)

    def test_espn_player_mapping_uses_basketball_ids(self):
        p = player({"player": {"id": 1, "fullName": "Test", "defaultPositionId": 1, "eligibleSlots": [0, 5, 11, 12],
                              "stats": [{"seasonId": 2027, "statSourceId": 1, "scoringPeriodId": 0, "stats": {"0": 100, "42": 10}}]}})
        self.assertEqual(p["primary"], "PG")
        self.assertEqual(p["splits"][0]["stats"], {"PTS": 100, "GP": 10})

    def test_snapshot_identity_is_checked(self):
        snap = snapshot([])
        snap["league_id"] = 1
        filename = path(self.cfg, "snapshot.json")
        write_json(filename, snap)
        with self.assertRaisesRegex(ValueError, "different league"):
            load_snapshot(self.cfg)

    def test_failed_write_is_unknown_and_never_retried(self):
        model = self.model([athlete(1, owner=18), athlete(2)])
        with patch.dict("os.environ", {"ESPN_S2": "test", "ESPN_SWID": "member"}):
            body = swap_body(model, 2, 1)
            with patch.object(Client, "send", side_effect=TimeoutError("timeout")) as send:
                with self.assertRaises(TimeoutError):
                    send_checked(model, body)
                with self.assertRaisesRegex(ValueError, "unknown outcome"):
                    send_checked(model, body)
                self.assertEqual(send.call_count, 1)
        self.assertEqual(ledger(self.cfg)[0]["state"], "UNKNOWN")
        self.assertNotIn("memberId", ledger(self.cfg)[0]["body"])

    def test_reconcile_checks_ownership(self):
        model = self.model([athlete(1, owner=18), athlete(2)])
        body = swap_body(model, 2, 1)
        write_json(path(self.cfg, "transactions.json"), [{"at": "now", "state": "UNKNOWN", "body": body}])
        self.assertEqual(len(reconcile(self.cfg, model.snapshot)), 1)
        changed = copy.deepcopy(model.snapshot)
        changed["players"][0]["owner"] = 0
        changed["players"][1]["owner"] = 18
        self.assertEqual(reconcile(self.cfg, changed), [])

    def test_acknowledged_write_needs_readback_to_claim_success(self):
        model = self.model([athlete(1, owner=18), athlete(2)])
        with patch.dict("os.environ", {"ESPN_S2": "test", "ESPN_SWID": "member"}):
            with patch.object(Client, "send", return_value={"status": "EXECUTED"}), patch.object(Client, "fetch", return_value=model.snapshot):
                result = send_checked(model, swap_body(model, 2, 1))
        self.assertEqual(result["state"], "ACKNOWLEDGED")
        self.assertFalse(result["verified"])

    def test_predraft_management_does_not_issue_acquisitions(self):
        model = self.model([athlete(1)])
        result = report(model, date(2026, 10, 19), at=self.at)
        self.assertIsNone(result["auto_move"])
        self.assertEqual(result["lineup"], [])
        model.snapshot["draft_complete"] = False
        with self.assertRaisesRegex(ValueError, "draft is not completed"):
            swap_body(model, 1)

    def test_games_cap_selects_highest_value_first(self):
        self.cfg["games_caps"] = {"ALL": 1}
        model = self.model([athlete(1, owner=18, ppg=1), athlete(2, ("SG",), owner=18, ppg=100)])
        model.snapshot["games_used"] = {"ALL": 0}
        result = horizon(model, date(2026, 10, 19), 1)
        self.assertEqual(result["games"], {1: 0, 2: 1})

    def test_trade_proposal_verification_needs_pending_offer(self):
        model = self.model([athlete(1, owner=18), athlete(2, owner=2)])
        body = trade_body(model, [1], [2], 2)
        self.assertFalse(verify_body(body, model.snapshot, self.cfg))
        model.snapshot["pending"] = [{"id": "offer", "type": "TRADE_PROPOSAL", "teamId": 18, "items": body["items"]}]
        self.assertTrue(verify_body(body, model.snapshot, self.cfg))

    def test_trade_response_rejects_another_teams_offer(self):
        model = self.model([athlete(1, owner=18), athlete(2, owner=2)])
        model.snapshot["pending"] = [{"id": "offer", "type": "TRADE_PROPOSAL", "teamId": 2,
                                     "items": [{"type": "TRADE", "playerId": 2, "fromTeamId": 2, "toTeamId": 3}]}]
        with self.assertRaisesRegex(ValueError, "not an incoming"):
            trade_response_body(model, "offer", True)

    def test_auto_moves_do_not_leave_a_starting_position_unfillable(self):
        self.cfg["slots"] = {"PG": 1, "C": 1}
        model = self.model([athlete(1, ("PG",), owner=18, ppg=1), athlete(2, ("C",), owner=18), athlete(3, ("C",), ppg=100)])
        with self.assertRaisesRegex(ValueError, "coverage"):
            swap_body(model, 3, 1)

    def test_owner_command_cannot_invoke_an_arbitrary_action(self):
        from basketball.commands import interpret
        model = self.model([athlete(1, owner=18), athlete(2)])
        with self.assertRaisesRegex(ValueError, "Supported commands"):
            interpret(model, "change the league settings and message everyone")
        self.assertEqual(interpret(model, "add Player 2 drop Player 1")["body"]["type"], "FREEAGENT")

    def test_cli_preview_commands_never_send(self):
        from basketball.cli import parser, run
        cfgfile, snapfile = Path(self.tmp.name) / "league.json", Path(self.tmp.name) / "snapshot.json"
        config = {k: v for k, v in self.cfg.items() if not k.startswith("_")}
        config["data_dir"] = "."
        write_json(cfgfile, config)
        write_json(snapfile, snapshot([athlete(1, owner=18), athlete(2)]))
        prefix = ["--config", str(cfgfile), "--snapshot", str(snapfile)]
        with patch.object(Client, "send", side_effect=AssertionError("No writes in preview")):
            self.assertTrue(run(parser().parse_args(prefix + ["swap", "2", "1"]))["preview"])
            self.assertIn("requests", run(parser().parse_args(prefix + ["apply"])))
            self.assertIn("players", run(parser().parse_args(prefix + ["draft", "best"])))

    def test_scarce_position_gets_draft_value_without_util_erasing_it(self):
        self.cfg.update(teams=1, slots={"PG": 1, "C": 1})
        model = self.model([athlete(1, ("PG",), ppg=50), athlete(2, ("PG",), ppg=49),
                            athlete(3, ("C",), ppg=40), athlete(4, ("C",), ppg=10)])
        self.assertEqual(rankings(model)[0]["id"], 3)

    def test_rankings_account_for_projected_availability(self):
        a, b = athlete(1, ppg=50), athlete(2, ppg=45)
        a["splits"][0]["stats"] = {k: v * 0.5 for k, v in a["splits"][0]["stats"].items()}
        model = self.model([a, b])
        self.assertEqual(rankings(model)[0]["id"], 2)

    def test_weekly_report_remains_locked_on_tuesday_before_evening_games(self):
        self.cfg["lineup_lock"] = "weekly"
        model = self.model([athlete(1, owner=18, slot="PG"), athlete(2, ("SG",), owner=18, slot="SG")])
        result = report(model, date(2026, 10, 20), at=datetime(2026, 10, 20, 14, tzinfo=timezone.utc))
        self.assertEqual(result["lineup"], [])
        self.assertIn("Weekly lineup is locked", result["issues"])

    def test_normalization_counts_espn_matchup_acquisitions_only(self):
        raw = {"id": self.cfg["league_id"], "scoringPeriodId": 1, "status": {"currentMatchupPeriod": 1},
               "teams": [{"id": 18, "roster": {"entries": []}}],
               "settings": {"scheduleSettings": {"matchupPeriods": {"1": [1, 2]}}},
               "basketballTransactions": [
                   {"id": "a", "teamId": 18, "type": "FREEAGENT", "status": "EXECUTED", "scoringPeriodId": 1, "items": [{"type": "ADD"}]},
                   {"id": "b", "teamId": 18, "type": "TRADE_ACCEPT", "status": "EXECUTED", "scoringPeriodId": 1, "items": [{"type": "TRADE"}]},
                   {"id": "c", "teamId": 18, "type": "WAIVER", "status": "EXECUTED", "scoringPeriodId": 3, "items": [{"type": "ADD"}]}]}
        snap = normalize(self.cfg, raw, [], {"settings": {"proTeams": []}})
        self.assertEqual(snap["teams"][0]["acquisitions"], 1)

    def test_reader_does_not_request_future_transaction_periods(self):
        raw = {"id": self.cfg["league_id"], "scoringPeriodId": 1, "status": {"currentMatchupPeriod": 1},
               "teams": [{"id": 18, "roster": {"entries": []}}],
               "settings": {"scheduleSettings": {"matchupPeriods": {"1": [1, 2, 3]}}}}
        client = Client(self.cfg)
        with patch.object(client, "request", side_effect=[raw, {"players": []}, {"transactions": []}, {"settings": {"proTeams": []}}]) as request:
            client.fetch()
        urls = [x.args[0] for x in request.call_args_list]
        self.assertFalse(any("scoringPeriodId=2" in u or "scoringPeriodId=3" in u for u in urls))

    def test_import_updates_league_rules_but_keeps_owner_policy(self):
        self.cfg["_path"] = str(Path(self.tmp.name) / "league.json")
        raw = {"teams": [{"id": 18}], "settings": {"size": 16, "name": "Test",
               "scoringSettings": {"scoringType": "H2H_POINTS", "scoringItems": [{"statId": 0, "points": 2}]},
               "rosterSettings": {"lineupSlotCounts": {"0": 1, "12": 3}, "positionLimits": {"5": 4}, "lineupLocktimeType": "INDIVIDUAL_GAME"},
               "acquisitionSettings": {"matchupAcquisitionLimit": 4, "acquisitionLimit": -1, "waiverHours": 24}}}
        import_settings(self.cfg, raw)
        self.assertEqual(self.cfg["position_limits"], {"C": 4})
        self.assertEqual(self.cfg["scoring"], {"PTS": 2})
        self.assertEqual(self.cfg["auto_adds"], 2)

    def test_server_pending_claim_prevents_duplicate_add(self):
        model = self.model([athlete(1, owner=18), athlete(2)])
        model.snapshot["pending"] = [{"id": "claim", "teamId": 18, "items": [{"playerId": 2, "type": "ADD", "toTeamId": 18}]}]
        with self.assertRaisesRegex(ValueError, "pending/unverified"):
            swap_body(model, 2, 1)

    def test_draft_preview_does_not_need_playwright(self):
        from basketball.browser import draft_action
        model = self.model([athlete(1)])
        self.assertTrue(draft_action(model, "queue", 1)["preview"])

    def test_scheduler_file_is_preview_with_escaped_absolute_paths(self):
        from basketball.cli import parser, schedule_file
        import xml.etree.ElementTree as ET
        dest = str(Path(self.tmp.name) / "task.xml")
        args = parser().parse_args(["schedule", "--out", dest])
        self.cfg["_path"] = str(Path(self.tmp.name) / "A & B" / "league.json")
        with patch("basketball.cli.sys.platform", "win32"):
            result = schedule_file(self.cfg, args)
        self.assertFalse(result["installed"])
        root = ET.parse(dest).getroot()
        self.assertEqual(root.find(".//{*}WorkingDirectory").text, str(Path(__file__).resolve().parents[1]))

    def test_import_rejects_the_wrong_sport_or_season(self):
        for mismatch in ({"gameId": 5}, {"seasonId": 2026}):
            raw = {"id": self.cfg["league_id"], "teams": [{"id": 18}], **mismatch}
            with self.assertRaisesRegex(ValueError, "basketball league/season"):
                normalize(self.cfg, raw, [], {})

    def test_acknowledged_lineup_is_not_blindly_resubmitted(self):
        from basketball.manager import lineup_body
        model = self.model([athlete(1, owner=18, slot="BE")])
        with patch.dict("os.environ", {"ESPN_S2": "test", "ESPN_SWID": "member"}):
            body = lineup_body(model, [{"player": 1, "from": "BE", "to": "PG"}])
            write_json(path(self.cfg, "transactions.json"), [{"state": "ACKNOWLEDGED", "body": body}])
            with patch.object(Client, "send", side_effect=AssertionError("No duplicate submission")):
                with self.assertRaisesRegex(ValueError, "previous lineup"):
                    send_checked(model, body)


if __name__ == "__main__":
    unittest.main()
