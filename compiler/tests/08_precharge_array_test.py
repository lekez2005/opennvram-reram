#!/usr/bin/env python3
"""
Run a regression test on a precharge array
"""

from testutils import OpenRamTest
import debug


class PrechargeTest(OpenRamTest):

    def runTest(self):
        from modules import precharge_array

        debug.info(2, "Checking 3 column precharge")
        pc = precharge_array.precharge_array(columns=3)
        self.local_check(pc)


OpenRamTest.run_tests(__name__)
