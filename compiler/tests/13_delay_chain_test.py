#!/usr/bin/env python3
"""
Run a test on a delay chain
"""

from testutils import OpenRamTest
import debug


class DelayChainTest(OpenRamTest):

    def runTest(self):
        from modules import delay_chain

        debug.info(2, "Testing delay_chain")
        a = delay_chain.delay_chain(fanout_list=[4, 4, 4, 4])
        self.local_check(a)

        debug.info(2, "Testing delay_chain")
        a = delay_chain.delay_chain(fanout_list=[4, 4, 4, 4], cells_per_row=3)
        self.local_check(a)


OpenRamTest.run_tests(__name__)
