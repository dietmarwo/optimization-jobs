#!/usr/bin/env python3
"""Acceptance boundaries for tutorial outcomes and independent analytic checks."""
import math
import unittest

from run import branin_value, check_evidence, oscillator_position


def record(claim, level, **extra):
    return [{'outcome': {'claim': claim, 'evidence': {'level': level, **extra}}}]


class EvidenceContract(unittest.TestCase):
    def test_positive_numerical_claim_needs_recheck(self):
        check_evidence(record('best_found', 'rechecked'))
        with self.assertRaises(AssertionError):
            check_evidence(record('best_found', 'claimed'))

    def test_infeasibility_exception_is_explicit_and_does_not_upgrade_evidence(self):
        with self.assertRaises(AssertionError):
            check_evidence(record('infeasible', 'claimed'))
        check_evidence(record('infeasible', 'claimed'), ('infeasible',))
        with self.assertRaises(AssertionError):
            check_evidence(record('best_found', 'claimed'), ('infeasible',))

    def test_refutation_fails_even_when_no_claim_survives(self):
        with self.assertRaises(AssertionError):
            check_evidence(record('none', 'rechecked', refuted=['false_optimality']))

    def test_a_checked_infeasible_point_is_a_valid_teaching_outcome(self):
        check_evidence(record('none', 'rechecked'))


class IndependentChecks(unittest.TestCase):
    def test_branin_at_analytic_minimum(self):
        self.assertAlmostEqual(branin_value([math.pi, 2.275]), 0.39788735772973816, places=10)

    def test_analytic_oscillator_initial_conditions_and_critical_case(self):
        for damping, stiffness in [(0.4, 2.3), (2., 1.), (3., 1.)]:
            self.assertAlmostEqual(oscillator_position(damping, stiffness, 0.), 1.)
            h = 1e-5
            derivative = (oscillator_position(damping, stiffness, h) -
                          oscillator_position(damping, stiffness, -h)) / (2*h)
            self.assertLess(abs(derivative), 1e-8)
        self.assertAlmostEqual(oscillator_position(2., 1., 2.), 3*math.exp(-2), places=12)


if __name__ == '__main__':
    unittest.main(verbosity=2)
