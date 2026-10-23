"""Formulation, independent oracle and malformed-data regressions."""
import copy
import itertools
import json
from pathlib import Path
import unittest

from rail import assess, encode, enumerate_orders, make_model, replay, schedule_order, validate_scenario


class RailChecks(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(Path(__file__).with_name('scenario.json').read_text())

    def matrix_feasible(self, model, x):
        if any(v < lo-1e-7 or v > hi+1e-7 for v, lo, hi in zip(x, model['variable_lower'], model['variable_upper'])):
            return False
        matrix = model['matrix']
        for row, upper in enumerate(model['row_upper']):
            activity = sum(matrix['values'][k] * x[matrix['indices'][k]]
                           for k in range(matrix['indptr'][row], matrix['indptr'][row+1]))
            if activity > upper + 1e-7:
                return False
        return True

    def test_all_orders_agree_with_mip_rows_for_each_policy(self):
        for cap, fifo in ((None, False), (8, False), (10, False), (10, True)):
            model, _ = make_model(self.data, cap, fifo)
            for order in itertools.permutations(range(6)):
                starts = schedule_order(self.data, order)
                self.assertEqual(self.matrix_feasible(model, encode(self.data, starts)),
                                 assess(self.data, starts, cap, fifo)['feasible'])

    def test_oracle_known_fixture_and_queue_constraint(self):
        for cap, fifo, expected in ((None, False, 7050), (8, False, 9840), (10, False, 7200), (10, True, 7950)):
            oracle = enumerate_orders(self.data, cap, fifo)
            self.assertEqual(oracle['orders_checked'], 720)
            self.assertEqual(oracle['best']['passenger_minutes'], expected)

    def test_independent_checker_catches_collisions_early_entry_and_wrong_queue(self):
        self.assertFalse(assess(self.data, [10, 5, 10, 20, 25, 30])['feasible'])
        self.assertFalse(assess(self.data, [0, 5, 10, 15, 20, 25])['feasible'])
        solution = enumerate_orders(self.data)['best']['starts']
        self.assertFalse(assess(self.data, solution, fifo=True)['feasible'])

    def test_infeasibility_from_incoming_delay(self):
        self.data['trains'][0]['ready'] += 5
        self.assertIsNone(enumerate_orders(self.data, cap=10)['best'])

    def test_stress_preserves_order_and_does_not_move_commitments_earlier(self):
        nominal = enumerate_orders(self.data, cap=10)['best']
        checked = replay(self.data, nominal, 5)
        self.assertEqual(checked['order'], nominal['order'])
        self.assertTrue(all(a >= b for a, b in zip(checked['starts'], nominal['starts'])))
        self.assertFalse(checked['feasible'])
        self.assertGreater(checked['max_delay'], 10)

    def test_malformed_and_ambiguous_scenarios_are_rejected(self):
        changes = [lambda d: d.update(clearance_minutes=0),
                   lambda d: d['trains'][0].update(passengers=0),
                   lambda d: d['trains'][0].update(ready=float('nan')),
                   lambda d: d['trains'][0].update(ready=True),
                   lambda d: d['trains'][1].update(id=d['trains'][0]['id']),
                   lambda d: d['trains'][0].update(direction='unknown'),
                   lambda d: d.update(unused_option=1)]
        for change in changes:
            data = copy.deepcopy(self.data); change(data)
            with self.assertRaises(ValueError):
                validate_scenario(data)


if __name__ == '__main__':
    unittest.main(verbosity=2)
