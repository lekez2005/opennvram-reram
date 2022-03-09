#!/usr/bin/env python3
"""
Run a regression test on a stacked wordline driver array.
"""

from testutils import OpenRamTest


class StackedWordlineDriverArrayTest(OpenRamTest):

    def test_stacked_wordline_driver(self):
        import debug
        from modules.stacked_wordline_driver_array import stacked_wordline_driver_array

        debug.info(2, "Testing 8-row wordline driver array")

        dut = stacked_wordline_driver_array("wordline_driver", 16, buffer_stages=[2, 4, 8])
        self.local_drc_check(dut)


StackedWordlineDriverArrayTest.run_tests(__name__)
