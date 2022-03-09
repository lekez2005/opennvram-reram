#!/usr/bin/env python3
"""
Run regression tests on a parameterized nor 2.  This module doesn't
generate a multi_finger 2-input nor gate.  It generates only a minimum
size 2-input nor gate.
"""

from testutils import OpenRamTest
import debug


class Pnor3Test(OpenRamTest):

    def test_pnor2(self):
        from pgates import pnor3

        debug.info(2, "Checking 2-input nor gate")
        dut = pnor3.pnor3(size=1, same_line_inputs=False)
        self.local_check(dut)

    def test_pnor2_same_line_inputs(self):
        from pgates import pnor2

        debug.info(2, "Checking 2-input nor gate")
        dut = pnor2.pnor2(size=1, same_line_inputs=True)
        self.local_check(dut)


OpenRamTest.run_tests(__name__)
