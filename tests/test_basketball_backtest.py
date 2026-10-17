"""Information boundaries and historical scoring, without network calls."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from basketball.backtest import (FIELDS, archive_order, digest, evaluate_picks,
                                input_model, name_key, parse_totals, prior_order, score, simulate)
from basketball.config import load, read_json, write_json
from basketball.drafting import board
from test_basketball import athlete


class BacktestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = load()
        self.cfg.update(_data=self.tmp.name, teams=2, slots={"PG": 1, "SG": 1, "BE": 1}, scoring={"PTS": 1})
        players = [athlete(i, ("PG", "SG"), ppg=30-i) for i in range(1, 9)]
        for p in players:
            p["splits"][0].update(season=2024, source=0)
        self.pack = {"season": 2025, "cutoff": "2024-09-01T00:00:00-04:00", "players": players}
        self.model = input_model(self.cfg, self.pack)
        self.model.cfg["_data"] = self.tmp.name

    def test_target_season_and_projection_leakage_are_rejected(self):
        for change in ({"season": 2025}, {"source": 1}):
            bad = copy.deepcopy(self.pack)
            bad["players"][0]["splits"][0].update(change)
            with self.assertRaisesRegex(ValueError, "Future information"):
                input_model(self.cfg, bad)

    def test_owner_overrides_cannot_enter_historical_experiment(self):
        self.cfg["adjustments"] = {"1": {"games": 82, "multiplier": 100}}
        self.assertEqual(input_model(self.cfg, self.pack).by_id[1]["fpg"], self.model.by_id[1]["fpg"])

    def test_actual_future_performance_does_not_change_draft(self):
        opponents = {team: prior_order(self.model) for team in (1, 2)}
        before = simulate(self.model, 1, None, opponents)
        outcomes = {p["id"]: {"stats": {"GP": 82, "PTS": p["id"] * 10000}} for p in self.model.players}
        result = evaluate_picks(before, 1, self.model, outcomes)
        self.assertGreater(result["total"], 10000)
        self.assertEqual(simulate(self.model, 1, None, opponents), before)

    def test_unplayed_retired_or_injured_pick_scores_zero(self):
        picks = [{"player": 1, "team": 1, "pick": 1}]
        result = evaluate_picks(picks, 1, self.model, {})
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["zero_games"], 1)

    def test_production_top_one_matches_full_board_at_each_draft_state(self):
        picks = []
        for pid in (None, 1, 2, 3):
            if pid:
                picks.append({"player": pid, "team": 2, "pick": len(picks)+1})
            write_json(Path(self.tmp.name) / "draft.json", {"picks": picks})
            self.assertEqual(board(self.model, count=1)["players"], board(self.model, count=100)["players"][:1])

    def test_archive_aliases_resolve_names_and_preserve_rank(self):
        pack = {"archive": {"ranks": {"2": "Player 2", "1": "Player 3", "3": "Missing Rookie"}}}
        order, unmatched = archive_order(pack, self.model, prior_order(self.model))
        self.assertEqual(order[:2], [3, 2])
        self.assertEqual(unmatched, ["Missing Rookie"])
        self.assertEqual(name_key("Jimmy Butler III"), name_key("Jimmy Butler"))
        self.assertEqual(name_key("Nicolas Claxton"), name_key("Nic Claxton"))

    def test_incomplete_or_wrong_season_stats_cannot_silently_score_zero(self):
        categories = [{"name": "all", "names": list(FIELDS)}]
        raw = {"requestedSeason": {"year": 2025, "type": {"type": 2}}, "pagination": {"pages": 1, "count": 1},
               "categories": categories, "athletes": [{"athlete": {"id": "1", "displayName": "Player 1"},
               "categories": [{"name": "all", "values": [1] * len(FIELDS)}]}]}
        self.assertEqual(parse_totals(raw, 2025)[1]["stats"]["GP"], 1)
        for bad in (dict(raw, pagination={"pages": 2, "count": 1}), dict(raw, pagination={"pages": 1, "count": 2})):
            with self.assertRaisesRegex(ValueError, "Incomplete"):
                parse_totals(bad, 2025)
        with self.assertRaisesRegex(ValueError, "different season"):
            parse_totals(raw, 2024)

    def test_tampered_decisions_stop_before_any_outcome_fetch(self):
        root = Path(self.tmp.name)
        write_json(root / "decisions.json", {"cases": []})
        (root / "decisions.sha256").write_text(digest({"cases": ["changed"]}))
        with patch("basketball.backtest.totals_for", side_effect=AssertionError("future fetch")):
            with self.assertRaisesRegex(ValueError, "decisions changed"):
                score(root, self.cfg)

    def test_tampered_inputs_stop_before_any_outcome_fetch(self):
        root = Path(self.tmp.name)
        evidence = {"config": {}, "input_sha256": {"2025": "wrong hash"}}
        write_json(root / "decisions.json", evidence)
        (root / "decisions.sha256").write_text(digest(evidence))
        write_json(root / "input-2025.json", self.pack)
        with patch("basketball.backtest.totals_for", side_effect=AssertionError("future fetch")):
            with self.assertRaisesRegex(ValueError, "inputs changed"):
                score(root, self.cfg)


if __name__ == "__main__":
    unittest.main()
