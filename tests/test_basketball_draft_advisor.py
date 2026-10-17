import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from basketball import bans
from basketball.cli import parser, run
from basketball.config import load, write_json
from basketball.draft_advisor import board, orders, expert_board, legal_choices
from basketball.espn import Client, player
from basketball.model import Model
from test_basketball import athlete, snapshot


class AdvisorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = load()
        self.cfg.update(_data=self.tmp.name, teams=2, slots={'UTIL': 1, 'BE': 2}, position_limits={})
        self.players = [dict(athlete(i), draft_rank=i, active=True) for i in range(1, 30)]
        self.model = Model(self.cfg, snapshot(self.players))
        for name, family in (('rotowire', 'RotoWire'), ('rotoworld', 'Rotoworld'), ('fantrax', 'FantraxHQ')):
            value = {'source': {'season': 2027, 'format': 'points', 'family': family, 'url': 'https://example.com'},
                     'status': 'prospective', 'rows': [{'name': 'Player 2', 'rank': 1}, {'name': 'Player 1', 'rank': 2},
                                                       {'name': 'Unmatched player', 'rank': 3}],
                     'retrieved_at': '2026-10-17T10:00:00Z', 'board_sha256': 'test'}
            write_json(self.root/'ranking-library/boards'/f'{name}-2027.json', value)
        patcher = patch('basketball.draft_advisor.checked_board')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_explicit_parser_is_read_only_and_supports_sources(self):
        args = parser().parse_args(['draft', 'hybrid', '--source', 'rotowire', '--slot', '1', '--verify'])
        self.assertTrue(args.verify)
        self.assertEqual(args.source, 'rotowire')
        with self.assertRaises(SystemExit), patch('sys.stderr'):
            parser().parse_args(['draft', 'hybrid', '--execute'])

    def test_published_rank_stays_missing_for_espn_tail_and_unmatched_names_are_visible(self):
        quality, market, published, details = orders(self.model, 'rotowire', self.root/'ranking-library')
        self.assertEqual(quality[:3], [2, 1, 3])
        self.assertEqual(market[:3], [1, 2, 3])
        self.assertNotIn(3, published['rotowire'])
        self.assertEqual(details[0]['unresolved_or_no_market_rank'], ['Unmatched player'])
        result = board(self.model, 'rotowire', slot=1)
        self.assertTrue(result['advisory_only'])
        self.assertFalse(result['availability_checked'])
        self.assertEqual(result['next_pick'], 4)
        self.assertFalse((self.root/'draft.json').exists())

    def test_bans_and_inactive_flags_exclude_candidates_even_without_projections(self):
        bans.edit(self.cfg, 'players', {'id': 2, 'name': 'Player 2'})
        self.players[0]['active'] = False
        for p in self.players:
            p['splits'] = []
        result = board(Model(self.cfg, snapshot(self.players)), 'rotowire', slot=1)
        self.assertNotIn(result['recommendation']['id'], {1, 2})

    def test_availability_rechecks_selected_player_and_recommends_allowed_alternative(self):
        def check(cfg, p):
            return {'id': p['id'], 'allowed': p['id'] != 2}
        with patch('basketball.draft_advisor.availability.check', side_effect=check):
            result = board(self.model, 'rotowire', slot=1, verify=True)
        self.assertTrue(result['availability_checked'])
        self.assertEqual(result['availability_checks'][0]['id'], 2)
        self.assertNotEqual(result['recommendation']['id'], 2)

    def test_known_turn_contiguous_history_and_team_ownership_are_required(self):
        with self.assertRaisesRegex(ValueError, 'known snake slot'):
            board(self.model)
        with self.assertRaisesRegex(ValueError, 'current snake turn'):
            board(self.model, slot=2)
        with self.assertRaisesRegex(ValueError, 'disagrees'):
            board(self.model, slot=1, current=2)
        write_json(self.root/'draft.json', {'picks': [{'pick': 2, 'player': 1, 'team': 18}]})
        with self.assertRaisesRegex(ValueError, 'consecutive'):
            board(self.model, slot=1)
        write_json(self.root/'draft.json', {'picks': [{'pick': 1, 'player': 1, 'team': self.cfg['team_id']}]})
        with self.assertRaisesRegex(ValueError, 'disagree'):
            board(self.model, slot=2)

    def test_missing_market_ranks_ambiguous_names_and_wrong_source_season_are_not_invented(self):
        duplicate = copy.deepcopy(self.players)
        duplicate[2]['name'] = 'Player 2'
        _, _, ranks, details = orders(Model(self.cfg, snapshot(duplicate)), 'rotowire', self.root/'ranking-library')
        self.assertNotIn(2, ranks['rotowire'])
        self.assertIn('Player 2', details[0]['unresolved_or_no_market_rank'])
        for p in duplicate:
            p.pop('draft_rank')
        with self.assertRaisesRegex(ValueError, 'STANDARD'):
            orders(Model(self.cfg, snapshot(duplicate)), 'rotowire', self.root)
        value = {'source': {'season': 2026, 'format': 'points'}, 'status': 'preseason'}
        write_json(self.root/'ranking-library/boards/rotowire-2027.json', value)
        with self.assertRaisesRegex(ValueError, 'current-season'):
            board(self.model, 'rotowire', slot=1)

    def test_consensus_contains_each_requested_publisher_once(self):
        quality, _, ranks, details = orders(self.model, 'consensus', self.root/'ranking-library')
        self.assertEqual(quality[:2], [2, 1])
        self.assertEqual(len(details), 3)
        self.assertEqual(set(ranks), {'rotowire', 'rotoworld', 'fantrax'})

    def test_slot_can_be_inferred_from_current_league_order(self):
        self.model.snapshot['settings'] = {'draftSettings': {'pickOrder': [self.cfg['team_id'], 99]}}
        self.assertEqual(board(self.model, 'rotowire')['pick'], 1)

    def test_cli_syncs_completed_snapshot_picks_before_advising_without_sending(self):
        config = dict(self.cfg, data_dir='.')
        write_json(self.root/'league.json', config)
        snap = snapshot(self.players)
        snap['draft'] = {'picks': [{'playerId': 1, 'teamId': 99, 'overallPickNumber': 1}]}
        write_json(self.root/'snapshot.json', snap)
        args = parser().parse_args(['--config', str(self.root/'league.json'), 'draft', 'hybrid', '--source', 'rotowire', '--slot', '2'])
        with patch.object(Client, 'request', side_effect=AssertionError('Advisor must not send')):
            result = run(args)
        self.assertEqual(result['pick'], 2)
        self.assertNotEqual(result['recommendation']['id'], 1)

    def test_normalizer_preserves_only_valid_standard_ranks(self):
        for rank, expected in ((5, 5), (None, None), (999, None), (0, None), (True, None), ('5', None)):
            p = player({'player': {'id': 1, 'fullName': 'Test', 'draftRanksByRankType': {'STANDARD': {'rank': rank}}}})
            self.assertEqual(p['draft_rank'], expected)

    def test_fetch_requests_standard_rank_fields_and_roster_overlay_preserves_them(self):
        raw = {'id': 1, 'fullName': 'Test', 'draftRanksByRankType': {'STANDARD': {'rank': 27}}}
        league = {'id': self.cfg['league_id'], 'seasonId': 2027, 'gameId': 3,
                  'teams': [{'id': self.cfg['team_id'], 'roster': {'entries': [{'playerPoolEntry': {'player': {'id': 1, 'fullName': 'Test'}}}]}}]}
        responses = [league, {'players': [{'player': raw}], 'totalPlayerCount': 1}, {}]
        with patch.object(Client, 'request', side_effect=responses) as request:
            snap = Client(self.cfg).fetch()
        self.assertEqual(snap['players'][0]['draft_rank'], 27)
        filters = request.call_args_list[1].kwargs['filters']['players']
        self.assertEqual(filters['sortDraftRanks']['value'], 'STANDARD')

    def test_expert_board_prefers_published_order_over_projection_and_allows_rookies(self):
        self.players[1]['splits'] = []
        model = Model(self.cfg, snapshot(self.players))
        result = expert_board(model, 'rotowire')
        self.assertFalse(model.by_id[2]['ranked'])
        self.assertEqual(result['players'][0]['id'], 2)
        self.assertEqual(result['players'][0]['published_expert_ranks'], {'rotowire': 1})
        bans.edit(self.cfg, 'players', {'id': 2, 'name': 'Player 2'})
        self.assertEqual(expert_board(model, 'rotowire')['players'][0]['id'], 1)

    def test_shared_legality_excludes_taken_foreign_owned_and_position_caps(self):
        self.cfg['position_limits'] = {'PG': 1}
        write_json(self.root/'draft.json', {'picks': [{'player': 1, 'team': self.cfg['team_id'], 'pick': 1}]})
        self.assertEqual(legal_choices(self.model, [1, 2, 3]), [])
        self.cfg['position_limits'] = {}
        self.model.by_id[3]['owner'] = 99
        self.assertEqual(legal_choices(self.model, [1, 2, 3]), [2])

    def test_expert_watch_is_explicit_and_browser_cannot_silently_use_model_strategy(self):
        args = parser().parse_args(['draft', 'watch', '--strategy', 'expert', '--source', 'rotowire', '--execute'])
        self.assertEqual(args.strategy, 'expert')
        args.transport = 'browser'
        with self.assertRaisesRegex(ValueError, 'API transport'):
            run(args)


if __name__ == '__main__':
    unittest.main()
