#!/usr/bin/env python3
"""
Run a regression test on a hierarchical_predecode2x4.
"""

from testutils import OpenRamTest
import debug


class HierarchicalPredecode2x4Test(OpenRamTest):

    def test_with_flops(self):
        from modules import hierarchical_predecode2x4 as pre

        debug.info(1, "Testing sample for hierarchy_predecode2x4 with flop")
        a = pre.hierarchical_predecode2x4(use_flops=True)
        self.local_drc_check(a)

    def test_no_flops(self):
        from modules import hierarchical_predecode2x4 as pre

        debug.info(1, "Testing sample for hierarchy_predecode2x4 without flop")
        a = pre.hierarchical_predecode2x4(use_flops=False)
        self.local_check(a)

    def test_even_buffer_stages(self):
        from modules import hierarchical_predecode2x4 as pre

        debug.info(1, "Testing sample for hierarchy_predecode2x4 with flop")
        a = pre.hierarchical_predecode2x4(use_flops=True, buffer_sizes=[1, 2, 4])
        self.local_check(a)

        
OpenRamTest.run_tests(__name__)
