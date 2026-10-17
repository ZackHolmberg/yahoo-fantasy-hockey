import unittest

from basketball.hybrid import Hybrid


class HybridTests(unittest.TestCase):
    def setUp(self):
        self.quality = list(range(1, 101))
        self.market = list(range(2, 101))+[1]
        self.h = Hybrid(self.quality, self.market)
        self.legal = lambda roster, pid: len(roster) < 12

    def test_can_wait_for_expert_favorite_while_taking_another_good_player(self):
        choice = self.h.choose(set(), [], 4, self.legal)
        self.assertTrue(choice['deferred'])
        self.assertEqual(choice['id'], 2)
        selected = next(r for r in choice['alternatives'] if r['id'] == 2)
        self.assertEqual(selected['next_choices']['espn'], 1)
        self.assertLess(selected['best_expert_survives_scenarios'], selected['scenario_count'])

    def test_never_falls_more_than_seven_quality_places_and_keeps_elite_when_demand_is_shared(self):
        h = Hybrid(self.quality, self.quality)
        choice = h.choose(set(), [], 20, self.legal)
        self.assertEqual(choice['id'], 1)
        self.assertTrue(all(r['quality_order'] <= 8 for r in choice['alternatives']))
        choice = h.choose(set(range(1, 20)), [], 20, self.legal)
        self.assertTrue(all(r['quality_order'] <= 27 for r in choice['alternatives']))

    def test_consecutive_and_final_picks_take_best_expert(self):
        for kwargs in ({'gap': 0}, {'gap': 10, 'final': True}):
            self.assertEqual(self.h.choose(set(), [], legal=self.legal, **kwargs)['id'], 1)

    def test_bans_apply_to_both_our_choices_but_not_opponent_forecasts(self):
        choice = self.h.choose(set(), [], 4, self.legal, excluded={2})
        self.assertNotEqual(choice['id'], 2)
        row = next(r for r in choice['alternatives'] if r['id'] == 1)
        # ESPN opponents still select banned-for-us player 2 within those four picks.
        self.assertEqual(row['next_choices']['espn'], 6)
        self.assertTrue(all(2 not in r['next_choices'].values() for r in choice['alternatives']))

    def test_next_choice_respects_roster_constraints_and_taken_players(self):
        def legal(roster, pid):
            return not (pid % 2 == 0 and any(p % 2 == 0 for p in roster))
        choice = self.h.choose({1, 3}, [100], 4, legal)
        for row in choice['alternatives']:
            self.assertEqual(row['id'] % 2, 1)
            for pid in row['next_choices'].values():
                self.assertNotIn(pid, {1, 3})
                self.assertEqual(pid % 2, 1)

    def test_scenario_exhaustion_is_explicit_greedy_fallback_and_deterministic(self):
        h = Hybrid([1, 2], [2, 1])
        first = h.choose(set(), [], 10, self.legal)
        self.assertEqual(first['id'], 1)
        self.assertTrue(all(r['pair_utility'] is None for r in first['alternatives']))
        self.assertEqual(first, h.choose(set(), [], 10, self.legal))

    def test_invalid_inputs_and_full_roster_fail(self):
        for quality, market in (([], []), ([1, 1], [1, 2]), ([1], [2])):
            with self.assertRaises(ValueError):
                Hybrid(quality, market)
        with self.assertRaises(ValueError):
            self.h.choose(set(), [], -1, self.legal)
        with self.assertRaises(ValueError):
            self.h.choose(set(), [1]*12, 4, self.legal)


if __name__ == '__main__':
    unittest.main()
