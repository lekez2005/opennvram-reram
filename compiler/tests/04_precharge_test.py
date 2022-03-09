#!/usr/bin/env python3
"""
Run a regression test on a precharge cell
"""

from testutils import OpenRamTest
import debug


class PrechargeTest(OpenRamTest):

    def runTest(self):
        from modules import precharge

        debug.info(2, "Checking precharge")
        tx = precharge.precharge(name="precharge", size=1)
        self.local_check(tx)


OpenRamTest.run_tests(__name__)
