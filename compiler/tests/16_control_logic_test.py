#!/usr/bin/env python3
"""
Run a regression test on a control_logic
"""

from testutils import OpenRamTest
import debug


class ControlLogicTest(OpenRamTest):

    def runTest(self):
        from modules import control_logic

        debug.info(1, "Testing sample for control_logic")
        a = control_logic.control_logic(num_rows=128)
        self.local_check(a)


OpenRamTest.run_tests(__name__)
