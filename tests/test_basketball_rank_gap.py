import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from basketball.backtest import digest, input_model
from basketball.config import load, write_json
from basketball.rank_gap import api_ranks, choose, locked, ranking, score, simulate, sources
from basketball.strategy_lab import grade
from test_basketball import athlete


class RankGapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = load()
        self.cfg.update(_data=self.tmp.name, teams=2, slots={"UTIL": 3}, position_limits={}, scoring={"PTS": 1})
        players = [athlete(i, ("PG",), ppg=40-i) for i in range(1, 13)]
        for p in players:
            p["splits"][0].update(season=2023, source=0)
        self.pack = {"season": 2024, "cutoff": "2023-10-23T00:00:00-04:00", "players": players}
        self.model = input_model(self.cfg, self.pack)
        self.expert = {1: 1, 2: 2, 3: 30}
        self.market = {1: 1, 2: 8, 3: 90}
        self.order = list(range(1, 13))

    def test_sign_and_window_prevent_deep_reach(self):
        args = (self.model, [], set())
        best, _ = choose(*args, "expert_best", self.expert, self.market, self.order)
        deep, trace = choose(*args, "gap_all", self.expert, self.market, self.order)
        near, _ = choose(*args, "gap_window", self.expert, self.market, self.order)
        self.assertEqual((best, deep, near), (1, 3, 2))
        self.assertEqual(trace["gap"], -60)
        self.assertEqual(trace["best_expert_available"]["id"], 1)

    def test_missing_rank_is_not_a_bargain_and_positive_gap_falls_back(self):
        pid, trace = choose(self.model, [], set(), "gap_all", self.expert, {1: 1}, self.order)
        self.assertEqual(pid, 1)
        self.assertTrue(trace["fallback"])
        self.assertEqual(trace["best_gaps_available"], [])
        _, trace = choose(self.model, [], {1, 2, 3}, "gap_all", self.expert, self.market, self.order)
        self.assertIsNone(trace["gap"])

    def test_drafted_player_and_roster_illegal_player_are_excluded(self):
        self.model.cfg.update(slots={"PG": 1, "C": 1, "BE": 1}, position_limits={"C": 1})
        for pid in (2, 3):
            self.model.by_id[pid].update(primary="C", eligible=["C", "UTIL", "BE"])
        pid, trace = choose(self.model, [self.model.by_id[2]], {1, 2}, "gap_all", self.expert, self.market, self.order)
        self.assertNotEqual(pid, 3)
        self.assertEqual(trace["best_gaps_available"], [])

    def test_api_parser_rejects_sentinel_invalid_and_duplicate_ids(self):
        def p(pid, rank):
            return {"id": pid, "draftRanksByRankType": {"STANDARD": {"rank": rank}}}
        self.assertEqual(api_ranks([p(1, 20), p(2, 999), p(3, True), p(4, -1), p(5, None)]), {1: 20})
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            api_ranks([p(1, 20), p(1, 21)])
        with self.assertRaisesRegex(ValueError, "No valid"):
            api_ranks([p(1, 999)])

    def test_full_snake_draft_unique_and_outcomes_do_not_change_choices(self):
        opponents = {1: self.order, 2: self.order}
        args = (self.model, 1, "gap_window", self.expert, self.market, self.order, opponents)
        first, trace = simulate(*args)
        self.assertEqual(len(trace), 3)
        self.assertEqual([r["pick"] for r in trace], [1, 4, 5])
        all_ids = [pid for roster in first.values() for pid in roster]
        self.assertEqual(len(all_ids), len(set(all_ids)))
        before = grade(self.model, first["1"], {})
        outcomes = {pid: {"stats": {"GP": 82, "PTS": pid*1000}} for pid in self.order}
        self.assertNotEqual(before, grade(self.model, first["1"], outcomes))
        self.assertEqual((first, trace), simulate(*args))

    def test_prior_tail_has_no_fake_gap_and_cannot_reintroduce_inactive_without_board(self):
        pack = copy.deepcopy(self.pack)
        pack["players"][11]["splits"][0]["season"] = 2022
        model = input_model(self.cfg, pack)
        expert, market, eorder, morder = ranking(model, {"expert": {"3": 1}, "market": {"2": 1}})
        self.assertEqual((eorder[0], morder[0]), (3, 2))
        self.assertNotIn(12, eorder)
        self.assertNotIn(1, expert)
        self.assertNotIn(1, market)

    def test_lock_tampering_stops_before_outcomes_are_read(self):
        inputs = [{"season": 2024}]
        evidence = {"source_sha256": sources(), "inputs_sha256": digest(inputs), "cases": []}
        write_json(self.root / "inputs.json", inputs)
        write_json(self.root / "decisions.json", evidence)
        (self.root / "decisions.sha256").write_text(digest(evidence))
        self.assertEqual(locked(self.root)[0], evidence)
        write_json(self.root / "inputs.json", [{"season": 2025}])
        with patch("basketball.rank_gap.totals_for") as outcomes:
            with self.assertRaisesRegex(ValueError, "changed"):
                score(self.root, self.cfg, self.root)
            outcomes.assert_not_called()


if __name__ == "__main__":
    unittest.main()
