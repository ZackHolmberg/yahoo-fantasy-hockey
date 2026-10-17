"""Targeted strategy experiment legality, isolation and preregistration tests."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from basketball.backtest import digest, input_model
from basketball.config import active_slots, load, read_json, write_json
from basketball.planner import assign, legal_roster
from basketball.strategy_lab import (STRATEGIES, choose, espn_ranks, features, grade, locked,
                                     score, simulate, source_hashes, values)
from test_basketball import athlete


class StrategyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = load()
        self.cfg.update(_data=self.tmp.name, teams=2, slots={"PG": 1, "C": 1, "BE": 1}, position_limits={"C": 1}, scoring={"PTS": 1})
        players = [athlete(i, ("PG",) if i % 2 else ("C",), ppg=40-i) for i in range(1, 13)]
        for p in players:
            p["splits"][0].update(season=2023, source=0)
            p["expert_rank"] = p["id"]
        self.pack = {"season": 2024, "cutoff": "2023-10-23T00:00:00-04:00", "players": players}
        self.model = input_model(self.cfg, self.pack)
        self.f, self.market = features(self.model)
        self.opponents = {1: self.market, 2: list(reversed(self.market))}

    def test_every_strategy_completes_legal_unique_rosters_with_center_cap(self):
        for policy in STRATEGIES + ("consensus_rank", "projection_total"):
            rosters = simulate(self.model, 1, policy, self.f, self.market, self.opponents)
            all_ids = [pid for ids in rosters.values() for pid in ids]
            self.assertEqual(len(all_ids), len(set(all_ids)))
            for ids in rosters.values():
                players = [self.model.by_id[pid] for pid in ids]
                self.assertTrue(legal_roster(players, self.cfg), policy)
                self.assertEqual(len(assign(players, active_slots(self.cfg))), 2)

    def test_actual_results_can_change_grade_but_not_choices(self):
        before = simulate(self.model, 1, "market_patience", self.f, self.market, self.opponents)
        outcomes = {pid: {"stats": {"GP": 82, "PTS": 100000*pid}} for pid in self.model.by_id}
        self.assertNotEqual(grade(self.model, before["1"], {})["total"], grade(self.model, before["1"], outcomes)["total"])
        self.assertEqual(before, simulate(self.model, 1, "market_patience", self.f, self.market, self.opponents))
        bad = copy.deepcopy(self.pack)
        bad["players"][0]["splits"][0]["season"] = 2024
        with self.assertRaisesRegex(ValueError, "Future information"):
            input_model(self.cfg, bad)

    def test_missing_recent_games_excluded_unless_published_before_draft(self):
        pack = copy.deepcopy(self.pack)
        pack["players"][0]["splits"][0]["season"] = 2022
        pack["players"][0]["expert_rank"] = None
        f, _ = features(input_model(self.cfg, pack))
        self.assertIn(1, values(f, "history_blend"))
        self.assertNotIn(1, values(f, "recent_gate"))
        pack["players"][0]["expert_rank"] = 5
        f, _ = features(input_model(self.cfg, pack))
        self.assertIn(1, values(f, "recent_gate"))

    def test_rookie_uses_prior_neighbors_without_inventing_historical_games(self):
        pack = copy.deepcopy(self.pack)
        pack["players"][0]["splits"] = []
        model = input_model(self.cfg, pack)
        f, _ = features(model)
        self.assertGreater(f[1]["durable"], 0)
        self.assertEqual(f[1]["blend"], 0)
        self.assertEqual(model.by_id[1]["splits"], [])
        self.assertTrue(f[1]["screened"])

    def test_lookahead_can_save_a_player_expected_to_survive(self):
        # Greedy picks A (100), but market will take B (99), leaving C (1).
        # Picking B now preserves A for a stronger two-pick result.
        model = copy.copy(self.model)
        model.cfg = dict(self.cfg, slots={"UTIL": 2}, position_limits={})
        scores = {1: 100, 2: 99, 3: 1}
        self.assertEqual(choose(model, [1, 2, 3], [], set(), scores, "market_patience", [2, 3, 1], 1), 2)
        self.assertEqual(choose(model, [1, 2, 3], [], set(), scores, "risk_blend", [2, 3, 1], 1), 1)

    def test_rank_parser_rejects_partial_and_duplicate_archives(self):
        text = "1. Player A, Den C C1 2. Player B, Bos PG/SG PG1"
        self.assertEqual(espn_ranks(text, 2)[2]["positions"], ["PG", "SG"])
        for bad in (text, text + "\n1. Duplicate, NY SF"):
            with self.assertRaises(ValueError):
                espn_ranks(bad, 3)

    def test_locked_sources_and_inputs_reject_tampering(self):
        write_json(self.root / "input-2024.json", self.pack)
        evidence = {"source_sha256": source_hashes(), "inputs": {"2024": digest(self.pack)}, "cases": []}
        write_json(self.root / "decisions.json", evidence)
        (self.root / "decisions.sha256").write_text(digest(evidence))
        self.assertEqual(locked(self.root), evidence)
        write_json(self.root / "input-2024.json", {**self.pack, "players": []})
        with self.assertRaisesRegex(ValueError, "Inputs changed"):
            locked(self.root)

    def test_heldout_results_require_frozen_selection_before_outcome_fetch(self):
        evidence = {"cases": [], "config": {}}
        with patch("basketball.strategy_lab.locked", return_value=evidence), \
                patch("basketball.strategy_lab.totals_for", side_effect=AssertionError("outcomes accessed")):
            with self.assertRaisesRegex(ValueError, "Freeze development"):
                score(self.root, self.cfg, self.root, "test")

    def test_development_fetches_only_development_outcomes_and_freezes_choice(self):
        cases = []
        for year in (2023, 2024, 2025):
            for policy in STRATEGIES:
                cases.append({"season": year, "family": "expert", "seed": -1, "slot": 1,
                              "strategy": policy, "rosters": {"1": [1, 2, 3], "2": [4, 5, 6]}})
            write_json(self.root / f"input-{year}.json", self.pack)
        evidence = {"config": {}, "cases": cases}
        with patch("basketball.strategy_lab.locked", return_value=evidence), \
                patch("basketball.strategy_lab.input_model", return_value=self.model), \
                patch("basketball.strategy_lab.totals_for", return_value={1: {"stats": {"GP": 60, "PTS": 100}}}) as fetch:
            score(self.root, self.cfg, self.root, "develop")
        self.assertEqual([call.args[0] for call in fetch.call_args_list], [2023, 2024, 2025])
        selection = read_json(self.root / "selection.json")
        self.assertEqual(digest(selection), (self.root / "selection.sha256").read_text().strip())


if __name__ == "__main__":
    unittest.main()
