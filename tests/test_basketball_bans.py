"""Hard draft exclusions across recommendations, current evidence and transports."""
import unittest
from unittest.mock import patch

from basketball import bans
from basketball.availability import check, verified_choice, review_risk
from basketball.browser import draft_action
from basketball.cli import parser, run
from basketball.config import path, read_json, write_json
from basketball.draft_api import preview
import test_basketball_draft_api as draft_fixtures
import test_basketball_availability as availability_fixtures


class BanTests(unittest.TestCase):
    setUp = draft_fixtures.DraftApiTests.setUp
    room = draft_fixtures.DraftApiTests.room

    def ban(self, pid=1):
        return bans.edit(self.cfg, 'players', {'id': pid, 'name': self.model.by_id[pid]['name']})

    def test_edit_remove_idempotent_and_ids_survive_trades_and_renaming(self):
        self.assertEqual(bans.listing(self.cfg)['players'], [])
        self.ban()
        self.ban()
        self.assertEqual(len(bans.listing(self.cfg)['players']), 1)
        changed = dict(self.model.by_id[1], team='99', name='Renamed')
        with self.assertRaises(bans.BannedPlayer):
            bans.require(self.cfg, changed)
        bans.remove(self.cfg, 'players', '1')
        bans.require(self.cfg, changed)

    def test_team_ban_affects_all_members_and_current_public_team(self):
        bans.edit(self.cfg, 'teams', {'id': 99, 'name': 'Test Team', 'abbreviation': 'TST'})
        for pid in (1, 2):
            with self.assertRaises(bans.BannedPlayer):
                bans.require(self.cfg, dict(self.model.by_id[pid], team='99'))
        with self.assertRaises(bans.BannedPlayer):
            bans.require(self.cfg, self.model.by_id[1], current_team='99')
        bans.require(self.cfg, dict(self.model.by_id[1], team='98'))

    def test_board_refills_after_exclusions_and_auto_choice_skips_bans(self):
        self.ban()
        rows = bans.board(self.model, count=1)['players']
        self.assertEqual(len(rows), 1)
        self.assertNotEqual(rows[0]['id'], 1)
        with patch('basketball.availability.check', return_value={'allowed': True}) as checks:
            chosen, _ = verified_choice(self.model)
        self.assertNotEqual(chosen['id'], 1)
        self.assertNotEqual(checks.call_args.args[1]['id'], 1)

    def test_player_ban_blocks_api_pick_queue_bid_and_browser_before_send(self):
        self.ban()
        for action in ('pick', 'queue', 'bid'):
            room = self.room()
            with self.assertRaises(bans.BannedPlayer):
                room.execute(action, 1, 2)
            self.assertFalse(any(c.startswith(('SELECT ', 'BID ', 'DRAFT_LIST ')) for c in room.socket.sent))
            self.assertIsNone(read_json(path(self.cfg, 'draft-write.json')))
            with self.assertRaises(bans.BannedPlayer):
                draft_action(self.model, action, 1, execute=True, bid=2)
            with self.assertRaises(bans.BannedPlayer):
                preview(self.model, action, 1, bid=2)

    def test_ban_added_during_verification_blocks_submission(self):
        room = self.room()
        def verify(*args):
            self.ban()
            return {'allowed': True}
        with patch('basketball.draft_api.availability.require', side_effect=verify):
            with self.assertRaises(bans.BannedPlayer):
                room.execute('pick', 1)
        self.assertFalse(any(c.startswith('SELECT ') for c in room.socket.sent))
        self.assertIsNone(read_json(path(self.cfg, 'draft-write.json')))

    def test_current_public_team_ban_blocks_despite_stale_fantasy_team(self):
        room = self.room()
        bans.edit(self.cfg, 'teams', {'id': 99, 'name': 'Test Team'})
        with patch('basketball.draft_api.availability.require', return_value={'allowed': True, 'team': '99'}):
            with self.assertRaises(bans.BannedPlayer):
                room.execute('pick', 1)
        self.assertFalse(any(c.startswith('SELECT ') for c in room.socket.sent))

    def test_malformed_policy_blocks_instead_of_becoming_empty(self):
        for bad in ({'version': 2}, {'version': 1, 'players': [{'id': '1', 'name': 'A'}], 'teams': []}):
            write_json(path(self.cfg, 'draft-bans.json'), bad)
            with self.assertRaises(ValueError):
                bans.board(self.model)
            room = self.room()
            with self.assertRaises(ValueError):
                room.execute('pick', 1)
            self.assertFalse(any(c.startswith('SELECT ') for c in room.socket.sent))

    def test_cli_list_add_remove_work_offline_and_during_watch(self):
        with patch('basketball.cli.load', return_value=self.cfg), patch('basketball.cli.load_snapshot') as snapshot:
            self.assertEqual(run(parser().parse_args(['draft', 'bans']))['players'], [])
            run(parser().parse_args(['draft', 'ban', 'player', '3468']))
            result = run(parser().parse_args(['draft', 'unban', 'player', '3468']))
            self.assertEqual(result['players'], [])
            snapshot.assert_not_called()

    def test_cli_rankings_and_cheatsheet_filter_bans(self):
        self.ban()
        with patch('basketball.cli.load', return_value=self.cfg), patch('basketball.cli.load_snapshot', return_value=self.model.snapshot):
            ranked = run(parser().parse_args(['rankings', '--limit', '1']))
            self.assertEqual(len(ranked), 1)
            self.assertNotEqual(ranked[0]['id'], 1)
            output = str(path(self.cfg, 'sheet.md'))
            run(parser().parse_args(['cheatsheet', '--out', output]))
            self.assertNotIn(self.model.by_id[1]['name'], path(self.cfg, 'sheet.md').read_text(encoding='utf-8'))

    def test_team_catalog_handles_alias_full_name_and_ambiguity(self):
        rows = [{'id': '9', 'displayName': 'Golden State Warriors', 'abbreviation': 'GS', 'location': 'Golden State'},
                {'id': '13', 'displayName': 'Los Angeles Lakers', 'abbreviation': 'LAL', 'location': 'Los Angeles'},
                {'id': '12', 'displayName': 'LA Clippers', 'abbreviation': 'LAC', 'location': 'Los Angeles'}]
        raw = {'sports': [{'leagues': [{'teams': [{'team': p} for p in rows]}]}]}
        with patch('basketball.availability.Sources.get', return_value=raw):
            self.assertEqual(bans.team(self.cfg, 'gsw')['id'], 9)
            self.assertEqual(bans.team(self.cfg, 'Los Angeles Lakers')['id'], 13)
            with self.assertRaisesRegex(ValueError, 'exactly one'):
                bans.team(self.cfg, 'Los Angeles')
        bans.edit(self.cfg, 'teams', {'id': 9, 'name': 'Golden State Warriors', 'abbreviation': 'GS'})
        self.assertEqual(bans.remove(self.cfg, 'teams', 'GSW')['teams'], [])


class BanAvailabilityTests(unittest.TestCase):
    setUp = availability_fixtures.AvailabilityTests.setUp

    def test_ban_cannot_be_overridden_by_injury_risk_review(self):
        bans.edit(self.cfg, 'players', {'id': 1, 'name': 'Player'})
        with patch('basketball.availability.Sources', return_value=self.source):
            report = check(self.cfg, self.player, sources=self.source)
            self.assertEqual(report['status'], 'blocked')
            self.assertFalse(report['allowed'])
            self.assertEqual(report['sources'], [])
            with self.assertRaisesRegex(ValueError, 'cannot be overridden'):
                review_risk(self.cfg, self.player, 'Accept risk', 2)

    def test_public_team_ban_overrides_accepted_injury_review(self):
        bans.edit(self.cfg, 'teams', {'id': 1, 'name': 'Current Team'})
        player = dict(self.player, team='0')
        result = check(self.cfg, player, sources=self.source)
        self.assertEqual(result['status'], 'blocked')
        self.assertFalse(result['allowed'])
        self.assertIn('team ban', result['reasons'][0])


if __name__ == '__main__':
    unittest.main()
