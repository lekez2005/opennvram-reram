#!/usr/bin/env python3
"""
Run a test on a delay chain
"""

from testutils import OpenRamTest
import debug


class ReplicaBitlineTest(OpenRamTest):

    def runTest(self):
        from modules import replica_bitline

        stages = 4
        fanout = 4
        rows = 13
        debug.info(2, "Testing RBL with {0} FO4 stages, {1} rows".format(stages, rows))
        a = replica_bitline.replica_bitline(stages, fanout, rows)
        self.local_check(a)

        stages = 8
        rows = 100
        debug.info(2, "Testing RBL with {0} FO4 stages, {1} rows".format(stages, rows))
        a = replica_bitline.replica_bitline(stages, fanout, rows)
        self.local_check(a)


OpenRamTest.run_tests(__name__)
