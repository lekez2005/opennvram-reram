#!/usr/bin/env python3
"""
Run a regression test on a hierarchical_predecode3x8.
"""

from testutils import OpenRamTest
import debug


class HierarchicalPredecode3x8Test(OpenRamTest):

    def test_with_flop(self):
        from modules import hierarchical_predecode3x8 as pre

        debug.info(1, "Testing sample for hierarchy_predecode3x8 with flop")
        a = pre.hierarchical_predecode3x8(use_flops=True)
        self.local_check(a)

    def test_with_no_flop(self):
        from modules import hierarchical_predecode3x8 as pre

        debug.info(1, "Testing sample for hierarchy_predecode3x8 without flop")
        a = pre.hierarchical_predecode3x8(use_flops=False)
        self.local_check(a)


OpenRamTest.run_tests(__name__)
