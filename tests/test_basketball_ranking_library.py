"""Ranking source dates, coverage, identity and pre-draft information boundaries."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from basketball.config import read_json, write_json
from basketball.ranking_library import (Page, build, checked_board, collect, dates, eligibility,
                                        parse_html, resolve_name, validate_rows)


class RankingLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.spec = {'id': 'test', 'season': 2025, 'family': 'Independent', 'url': 'https://example.invalid/board',
                     'parser': 'table', 'count': 2, 'format': 'points', 'basis': 'published expert order',
                     'title_pattern': '2024 Points', 'headers': ['Rank', 'Player', 'Pos', 'FPTS'],
                     'name_columns': ['Player'], 'rank_column': 'Rank', 'forecast_columns': ['FPTS']}
        self.html = ('<html><head><title>2024 Points Rankings</title></head><body>'
                     '<script type="application/ld+json">{"datePublished":"2024-10-01T12:00:00Z",'
                     '"dateModified":"2024-10-10T12:00:00Z"}</script><table><tr>'
                     '<th>Rank</th><th>Player</th><th>Pos</th><th>FPTS</th></tr>'
                     '<tr><td>1</td><td><a>Player A</a></td><td>PG</td><td>40</td></tr>'
                     '<tr><td>2</td><td>Player B</td><td>C</td><td>35.5</td></tr></table></body></html>')

    def collected(self):
        raw = self.root/'raw/test.html'
        raw.parent.mkdir(exist_ok=True)
        raw.write_text(self.html, encoding='utf-8')
        with patch('builtins.print'):
            collect(self.root, [self.spec])
        return read_json(self.root/'boards/test.json')

    def test_table_preserves_native_forecast_without_inventing_missing_stats(self):
        rows, evidence = parse_html(self.html, self.spec)
        self.assertEqual(rows[0], {'rank': 1, 'name': 'Player A', 'positions': ['PG'], 'forecast': {'FPTS': 40.0}})
        self.assertNotIn('FGA', rows[0]['forecast'])
        self.assertEqual(eligibility(self.spec, evidence)[0], 'preseason')

    def test_late_revision_category_format_and_prospective_capture_are_distinct(self):
        evidence = {'datePublished': '2024-10-01', 'dateModified': '2025-01-01'}
        self.assertEqual(eligibility(self.spec, evidence)[0], 'diagnostic')
        cat = dict(self.spec, format='categories')
        self.assertEqual(eligibility(cat, {'datePublished': '2024-10-01', 'dateModified': '2024-10-10'})[0], 'category_only')
        current = dict(self.spec, season=2027)
        self.assertEqual(eligibility(current, {'datePublished': '2026-09-01'}, '2026-10-17')[0], 'prospective')
        self.assertEqual(eligibility(current, {'datePublished': '2026-09-01'}, '2026-10-19')[0], 'diagnostic')

    def test_missing_ambiguous_and_invalid_dates_are_rejected(self):
        for text in ('{}', '{"datePublished":"2024-10-01","dateModified":"bad"}',
                     '{"datePublished":"2024-10-01","dateModified":"2024-10-02","x":{"dateModified":"2025-01-01"}}'):
            with self.assertRaises(ValueError):
                dates(text)
        with self.assertRaises(ValueError):
            dates('{"datePublished":"2024-10-01"}')
        self.assertEqual(dates('{"datePublished":"2026-09-01"}', allow_missing_modified=True), {'datePublished': '2026-09-01'})

    def test_timestamp_offsets_are_compared_as_instants_not_calendar_prefixes(self):
        evidence = {'datePublished': '2024-10-01T12:00:00Z', 'dateModified': '2024-10-20T23:00:00-07:00'}
        self.assertEqual(eligibility(self.spec, evidence)[0], 'diagnostic')
        with self.assertRaisesRegex(ValueError, 'timezone'):
            eligibility(self.spec, {'datePublished': '2024-10-01T12:00:00'})

    def test_duplicate_players_partial_boards_and_changed_headers_are_rejected(self):
        for text in (self.html.replace('Player B', 'Player A'), self.html.replace('<td>2</td>', '<td>1</td>'),
                     self.html.replace('<th>FPTS</th>', '<th>Actual FP</th>')):
            with self.assertRaises(ValueError):
                parse_html(text, self.spec)
        with self.assertRaises(ValueError):
            validate_rows([{'rank': 1, 'name': 'One'}], self.spec)

    def test_numbered_sections_preserve_explicit_rank_starts_and_stop_at_coverage(self):
        spec = dict(self.spec, parser='ordered', count=3, combine_lists=True, name_split=',')
        text = self.html[:self.html.index('<table>')] + '<ol><li>Player A, Team</li><li>Player B, Team</li></ol><ol start="3"><li>Player C, Team</li></ol><ol><li>Unrelated</li></ol>'
        rows, _ = parse_html(text, spec)
        self.assertEqual([(r['rank'], r['name']) for r in rows], [(1, 'Player A'), (2, 'Player B'), (3, 'Player C')])

    def test_native_category_ties_are_only_allowed_explicitly(self):
        rows = [{'rank': 1, 'name': 'A'}, {'rank': 1, 'name': 'B'}]
        with self.assertRaises(ValueError):
            validate_rows(rows, self.spec)
        self.assertEqual(validate_rows(rows, dict(self.spec, allow_ties=True)), rows)

    def test_wrong_title_cannot_be_accepted_from_unrelated_sidebar_text(self):
        with self.assertRaisesRegex(ValueError, 'Unexpected title'):
            parse_html(self.html.replace('<title>2024 Points Rankings</title>', '<title>2026 Current Rankings</title><svg><title>2024 Points</title></svg>'), self.spec)

    def test_prior_identity_disambiguates_fantasy_duplicates_without_target_stats(self):
        target = {'playera': {1, 999}, 'playerb': {2, 3}}
        self.assertEqual(resolve_name('Player A', target, {'playera': {1}}), 1)
        self.assertIsNone(resolve_name('Player B', target, {}))
        self.assertIsNone(resolve_name('Unknown', target, {}))

    def test_capture_is_reused_and_hash_tampering_is_detected(self):
        board = self.collected()
        checked_board(self.root, board)
        with patch('builtins.print'):
            collect(self.root, [self.spec])
        again = read_json(self.root/'boards/test.json')
        self.assertEqual(board['retrieved_at'], again['retrieved_at'])
        self.assertEqual(board['board_sha256'], again['board_sha256'])
        modified = copy.deepcopy(board)
        modified['rows'][0]['rank'] = 2
        with self.assertRaisesRegex(ValueError, 'Normalized board changed'):
            checked_board(self.root, modified)
        (self.root/'raw/test.html').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'source bytes changed'):
            checked_board(self.root, board)

    def test_build_reads_only_previous_seasons_and_prior_positions(self):
        self.collected()
        histories = {1: {'name': 'Player A', 'stats': {'GP': 70, 'PTS': 1000}}}
        prior = [{'id': 1, 'fullName': 'Player A', 'defaultPositionId': 1, 'eligibleSlots': [0, 5, 11, 12, 13]}]
        target = [{'id': 1, 'fullName': 'Player A', 'defaultPositionId': 5, 'eligibleSlots': [4]},
                  {'id': 2, 'fullName': 'Player B', 'defaultPositionId': 1, 'eligibleSlots': [0]}]
        def metadata(url, *args):
            return prior if '/2024/' in url else target
        with patch('basketball.ranking_library.totals_for', return_value=histories) as totals, \
             patch('basketball.ranking_library.get_json', side_effect=metadata), patch('builtins.print'):
            build(self.root, self.root, [2025])
        self.assertEqual([c.args[0] for c in totals.call_args_list], [2023, 2024])
        pack = read_json(self.root/'input-2025.json')
        players = {p['id']: p for p in pack['players']}
        self.assertEqual(players[1]['primary'], 'PG')
        self.assertEqual(players[2]['primary'], 'C')  # Published position, never target metadata's PG.
        self.assertEqual(players[2]['splits'], [])
        self.assertEqual(pack['ranking_boards']['test'], {'1': 1, '2': 2})
        self.assertEqual(players[1]['team'], '0')


if __name__ == '__main__':
    unittest.main()
