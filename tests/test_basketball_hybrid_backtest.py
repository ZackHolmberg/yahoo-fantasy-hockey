from functools import lru_cache
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from basketball.backtest import input_model
from basketball.config import load, read_json, write_json
from basketball.hybrid import Hybrid
from basketball.hybrid_backtest import draft, locked, score, simulate
from basketball.source_backtest import draft as baseline_draft
from basketball.strategy_lab import legal
from test_basketball import athlete


class HybridBacktestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = load()
        self.cfg.update(_data=self.tmp.name, teams=2, slots={'PG': 1, 'C': 1, 'BE': 1}, position_limits={'C': 1})
        players = [athlete(i, ('PG',) if i%2 else ('C',)) for i in range(1, 20)]
        for p in players:
            p['splits'] = [{'season': 2023, 'source': 0, 'stats': {'GP': 60, 'PTS': 1000-p['id']}}]
        self.pack = {'season': 2024, 'cutoff': '2023-10-23T00:00:00-04:00', 'players': players, 'baseline_source': 'espn',
                     'ranking_boards': {'espn': {str(i): i for i in range(1, 20)}, 'rw': {'3': 1, '1': 2, '2': 3}},
                     'sources': [{'id': ident, 'family': family, 'date_evidence': {'datePublished': '2023-09-01T00:00:00Z'}, 'basis': 'published expert order'}
                                 for ident, family in (('espn', 'ESPN'), ('rw', 'RotoWire'))]}
        self.model = input_model(self.cfg, self.pack)

    def test_full_league_is_unique_legal_deterministic_and_decisions_do_not_read_outcomes(self):
        order = list(range(1, 20))
        @lru_cache(None)
        def allowed(roster, pid):
            return legal(self.model, [self.model.by_id[p] for p in roster], pid)
        legal_fn = lambda roster, pid: allowed(tuple(roster), pid)
        args = self.model, 1, Hybrid(order, order), {1: order, 2: order}, legal_fn
        with patch('basketball.hybrid_backtest.totals_for') as outcomes:
            first = simulate(*args)
            self.assertEqual(first, simulate(*args))
            outcomes.assert_not_called()
        rosters, trace = first
        self.assertEqual(len(set(p for r in rosters.values() for p in r)), 6)
        self.assertEqual(rosters['1'], [p['id'] for p in trace])
        self.assertEqual([p['gap'] for p in trace], [2, 0, 2])

    def test_pairs_reuse_baseline_and_tampered_lock_prevents_outcome_reads(self):
        baseline = self.root/'baseline'
        write_json(baseline/'inputs.json', {'packs': [self.pack]})
        with patch('builtins.print'), patch('basketball.hybrid_backtest.YEARS', (2024,)):
            baseline_draft(baseline, self.cfg)
            result = draft(self.root, self.cfg, baseline)
            evidence, _ = locked(self.root, baseline)
            self.assertEqual(result['cases'], 60)
            self.assertEqual(result['new_drafts'], 24)
            outcomes = {i: {'stats': {'GP': 60, 'PTS': 1000+i}} for i in range(1, 20)}
            with patch('basketball.hybrid_backtest.totals_for', return_value=outcomes):
                result = score(self.root, self.cfg, baseline, self.root)
            self.assertEqual(next(r for r in result['aggregate'] if r['policy']=='espn')['gain_vs_espn'], 0)
            evidence['cases'][0]['rosters']['1'][0] = 999
            write_json(self.root/'decisions.json', evidence)
            with patch('basketball.hybrid_backtest.totals_for') as outcomes:
                with self.assertRaisesRegex(ValueError, 'changed'):
                    score(self.root, self.cfg, baseline, self.root)
                outcomes.assert_not_called()


if __name__ == '__main__':
    unittest.main()
