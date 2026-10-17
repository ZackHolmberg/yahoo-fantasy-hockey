import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from basketball.backtest import digest, input_model
from basketball.config import load, read_json, write_json
from basketball.source_backtest import draft, locked, preferences, primary_sources, score, simulate
from basketball.strategy_lab import grade
from test_basketball import athlete


class SourceBacktestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = load()
        self.cfg.update(_data=self.tmp.name, teams=2, slots={'PG': 1, 'C': 1, 'BE': 1}, position_limits={'C': 1}, scoring={'PTS': 1})
        players = [athlete(i, ('PG',) if i % 2 else ('C',), ppg=40-i) for i in range(1, 13)]
        for p in players:
            p['splits'][0].update(season=2023, source=0)
        def src(ident, family, date='2023-09-01T12:00:00Z', basis='published expert order'):
            return {'id': ident, 'family': family, 'date_evidence': {'datePublished': date}, 'basis': basis}
        self.pack = {'season': 2024, 'cutoff': '2023-10-23T00:00:00-04:00', 'players': players, 'baseline_source': 'espn',
                     'ranking_boards': {'espn': {str(i): i for i in range(1, 13)}, 'rw-old': {'2': 1, '1': 2},
                                        'rw-total': {'3': 1, '1': 2, '2': 3}, 'rw-pg': {'2': 1, '3': 2, '1': 3},
                                        'nbc': {'2': 1, '1': 2, '3': 3}},
                     'sources': [src('espn', 'ESPN'), src('rw-old', 'RotoWire', '2023-07-01T12:00:00Z'),
                                 src('rw-total', 'RotoWire'), src('rw-pg', 'RotoWire', '2023-10-01T12:00:00Z', 'projected points per game'),
                                 src('nbc', 'Rotoworld')]}
        self.model = input_model(self.cfg, self.pack)

    def test_missing_rank_uses_declared_espn_tail_without_inventing_published_ranks(self):
        policies, boards, _ = preferences(self.model, self.pack)
        self.assertEqual(policies['source:rw-old']['order'][:4], [2, 1, 3, 4])
        self.assertNotIn(3, boards['rw-old'])
        self.assertEqual(policies['source:rw-old']['coverage'], {1, 2})

    def test_consensus_uses_one_latest_non_pergame_board_per_publisher(self):
        primary = primary_sources(self.pack)
        self.assertEqual(primary, {'ESPN': 'espn', 'RotoWire': 'rw-total', 'Rotoworld': 'nbc'})
        policies, _, _ = preferences(self.model, self.pack)
        self.assertEqual(policies['publisher_consensus']['sources'], ['espn', 'nbc', 'rw-total'])
        self.assertEqual(policies['publisher_consensus']['order'][:3], [1, 2, 3])

    def test_all_sources_share_pool_and_old_unpublished_inactive_player_is_excluded(self):
        pack = copy.deepcopy(self.pack)
        pack['players'][-1]['splits'][0]['season'] = 2022
        for ranks in pack['ranking_boards'].values():
            ranks.pop('12', None)
            ranks.pop('11', None)
        model = input_model(self.cfg, pack)
        policies, _, _ = preferences(model, pack)
        expected = set(range(1, 12))
        for data in policies.values():
            self.assertEqual(set(data['order']), expected)

    def test_every_policy_drafts_unique_legal_rosters_and_is_outcome_isolated(self):
        policies, published, _ = preferences(self.model, self.pack)
        opponents = {team: policies['espn']['order'] for team in (1, 2)}
        for data in policies.values():
            args = (self.model, 1, data, opponents, published, published['espn'])
            first = simulate(*args)
            roster, trace = first
            self.assertEqual(len(trace), 3)
            self.assertEqual([p['id'] for p in trace], roster['1'])
            all_ids = [pid for ids in roster.values() for pid in ids]
            self.assertEqual(len(set(all_ids)), 6)
            for ids in roster.values():
                self.assertLessEqual(sum(self.model.by_id[pid]['primary']=='C' for pid in ids), 1)
            empty = grade(self.model, roster['1'], {})
            outcomes = {pid: {'stats': {'GP': 82, 'PTS': 10000*pid}} for pid in all_ids}
            self.assertNotEqual(empty, grade(self.model, roster['1'], outcomes))
            self.assertEqual(first, simulate(*args))

    def test_future_splits_are_rejected_before_preferences(self):
        bad = copy.deepcopy(self.pack)
        bad['players'][0]['splits'][0]['season'] = 2024
        with self.assertRaisesRegex(ValueError, 'Future information'):
            input_model(self.cfg, bad)

    def test_draft_lock_and_tampering_prevent_outcome_reads(self):
        write_json(self.root/'inputs.json', {'packs': [self.pack]})
        with patch('builtins.print'):
            result = draft(self.root, self.cfg)
        evidence, _ = locked(self.root)
        self.assertEqual(result['decision_sha256'], digest(evidence))
        # Identical ESPN/consensus orders share one field rather than duplicate it.
        self.assertEqual(len(evidence['cases']), 42)
        modified = read_json(self.root/'decisions.json')
        modified['cases'][0]['rosters']['1'][0] = 999
        write_json(self.root/'decisions.json', modified)
        with patch('basketball.source_backtest.totals_for') as outcomes:
            with self.assertRaisesRegex(ValueError, 'changed'):
                score(self.root, self.cfg, self.root)
            outcomes.assert_not_called()


if __name__ == '__main__':
    unittest.main()
