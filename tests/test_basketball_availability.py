"""Availability evidence, review expiry, and blocking draft commands before writes."""
import copy
from datetime import datetime, timedelta, timezone
import tempfile
import unittest
from unittest.mock import patch

from basketball.availability import PROFILE, SITE, Sources, athlete_id, check, require, review_risk, verified_choice
from basketball.config import load, path, read_json
from basketball.draft_api import Room
import test_basketball_draft_api as draft_fixtures


class AvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = load()
        self.cfg['_data'] = self.tmp.name
        self.at = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
        timer = patch('basketball.availability.now', return_value=self.at)
        timer.start()
        self.addCleanup(timer.stop)
        self.player = {'id': 1, 'name': 'Player', 'active': True, 'team': '1', 'status': 'ACTIVE'}
        self.profile = {'season': {'year': 2027}, 'athlete': {'id': '1', 'active': True, 'status': {'type': 'active'}, 'team': {'id': '1'}}}
        self.roster = {'season': {'year': 2027}, 'team': {'id': '1'}, 'timestamp': self.at.isoformat(),
                       'athletes': [{'id': '1', 'status': {'type': 'active'}, 'injuries': []}]}
        self.report = {'season': {'year': 2027}, 'status': 'success', 'timestamp': self.at.isoformat(), 'injuries': []}
        self.source = Sources(self.cfg)
        self.source.get = lambda url, refresh=False: copy.deepcopy({PROFILE+'1': self.profile, SITE+'teams/1/roster': self.roster, SITE+'injuries': self.report}[url])

    def injury(self, designation='GTD'):
        self.report['injuries'] = [{'injuries': [{'status': 'Day-To-Day', 'date': '2026-10-16T10:00Z',
            'shortComment': 'Player has a concern', 'details': {'fantasyStatus': {'abbreviation': designation}, 'returnDate': '2026-10-25'},
            'athlete': {'links': [{'href': 'https://www.espn.com/nba/player/_/id/1/player'}]}}]}]

    def result(self):
        return check(self.cfg, self.player, sources=self.source)

    def test_positive_membership_and_report_required_and_recorded(self):
        result = self.result()
        self.assertEqual(result['status'], 'clear')
        self.assertTrue(result['allowed'])
        self.assertEqual(len(result['sources']), 3)
        self.assertEqual(read_json(path(self.cfg, 'availability-checks.json'))['1'], result)

    def test_inactive_public_profile_overrules_active_fantasy_flag(self):
        self.profile['athlete']['active'] = False
        result = self.result()
        self.assertEqual(result['status'], 'blocked')
        self.assertFalse(result['allowed'])

    def test_season_out_is_blocked_and_temporary_injury_requires_review(self):
        self.injury('OFS')
        self.assertEqual(self.result()['status'], 'blocked')
        self.injury('GTD')
        self.assertEqual(self.result()['status'], 'review')

    def test_missing_stale_wrong_season_and_unrostered_never_clear(self):
        for mutate in (lambda: self.roster.update(timestamp=(self.at-timedelta(hours=1)).isoformat()),
                       lambda: self.report.update(season={'year': 2026}),
                       lambda: self.roster.update(athletes=[]),
                       lambda: self.roster['athletes'][0].pop('injuries'),
                       lambda: self.profile['athlete'].update(status={'type': 'free-agent'})):
            old = copy.deepcopy((self.profile, self.roster, self.report))
            mutate()
            self.assertFalse(self.result()['allowed'])
            self.profile, self.roster, self.report = old

    def test_review_is_bound_to_condition_and_expires(self):
        self.injury()
        with patch('basketball.availability.Sources', return_value=self.source):
            review_risk(self.cfg, self.player, 'Accept known short injury at this draft price', 2)
        self.assertEqual(self.result()['status'], 'risk_accepted')
        self.report['injuries'][0]['injuries'][0]['details']['returnDate'] = '2027-01-01'
        self.assertEqual(self.result()['status'], 'review')
        self.report['injuries'][0]['injuries'][0]['details']['returnDate'] = '2026-10-25'
        self.roster['timestamp'] = self.report['timestamp'] = (self.at+timedelta(hours=3)).isoformat()
        with patch('basketball.availability.now', return_value=self.at+timedelta(hours=3)):
            self.assertFalse(self.result()['allowed'])

    def test_hard_block_cannot_be_overridden(self):
        self.injury('OFS')
        with patch('basketball.availability.Sources', return_value=self.source):
            with self.assertRaisesRegex(ValueError, 'cannot be overridden'):
                review_risk(self.cfg, self.player, 'Ignore', 2)

    def test_source_failure_and_ambiguous_identity_fail_closed(self):
        self.source.get = lambda *args: (_ for _ in ()).throw(OSError('source unavailable'))
        self.assertEqual(self.result()['status'], 'unknown')
        with self.assertRaises(ValueError):
            athlete_id({'id': '1', 'links': [{'href': 'https://www.espn.com/nba/player/_/id/2/a'}]})

    def test_normalized_fantasy_active_flag_is_preserved(self):
        from basketball.espn import player
        self.assertIs(player({'id': 1, 'fullName': 'Retired', 'active': False})['active'], False)


class AvailabilityExecutionTests(unittest.TestCase):
    setUp = draft_fixtures.DraftApiTests.setUp
    room = draft_fixtures.DraftApiTests.room
    def test_gate_blocks_pick_queue_bid_before_journal_and_send(self):
        for action in ('pick', 'queue', 'bid'):
            room = self.room()
            with patch('basketball.draft_api.availability.require', side_effect=ValueError('Availability blocked')):
                with self.assertRaisesRegex(ValueError, 'Availability blocked'):
                    room.execute(action, 1, 2)
            self.assertFalse(any(c.startswith(('SELECT ', 'BID ', 'DRAFT_LIST ')) for c in room.socket.sent))
            self.assertIsNone(read_json(path(self.cfg, 'draft-write.json')))

    def test_clock_is_rechecked_after_availability_read(self):
        room = self.room()
        def consume_clock(*args):
            room.deadline = 0
            return {'allowed': True}
        with patch('basketball.draft_api.availability.require', side_effect=consume_clock):
            with self.assertRaisesRegex(ValueError, '25 seconds'):
                room.execute('pick', 1)
        self.assertFalse(any(c.startswith('SELECT ') for c in room.socket.sent))

    def test_auto_choice_skips_unverified_top_player(self):
        with patch('basketball.availability.check', side_effect=[{'allowed': False}, {'allowed': True}]):
            chosen, checks = verified_choice(self.model)
        self.assertEqual(chosen['id'], 2)
        self.assertEqual(len(checks), 2)

    def test_auto_choice_can_follow_expert_order_instead_of_model_order(self):
        with patch('basketball.availability.check', side_effect=[{'allowed': False}, {'allowed': True}]):
            chosen, checks = verified_choice(self.model, [{'id': 3}, {'id': 2}])
        self.assertEqual(chosen['id'], 2)
        self.assertEqual(len(checks), 2)

    def test_browser_execution_uses_same_gate_before_browser_start(self):
        from basketball.browser import draft_action
        with patch('basketball.browser.availability.require', side_effect=ValueError('Availability blocked')):
            with self.assertRaisesRegex(ValueError, 'Availability blocked'):
                draft_action(self.model, 'queue', 1, execute=True)


if __name__ == '__main__':
    unittest.main()
