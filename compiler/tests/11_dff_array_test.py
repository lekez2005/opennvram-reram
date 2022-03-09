#!/usr/bin/env python3
"""
Run a regression test on a dff_array.
"""

import unittest
from testutils import OpenRamTest
import debug


@unittest.skip("SKIPPING 04_driver_test")
class DffArrayTest(OpenRamTest):

    def runTest(self):

        from modules import dff_array

        debug.info(2, "Testing dff_array for 3x3")
        a = dff_array.dff_array(rows=3, columns=3)
        self.local_check(a)

        debug.info(2, "Testing dff_array for 1x3")
        a = dff_array.dff_array(rows=1, columns=3)
        self.local_check(a)

        debug.info(2, "Testing dff_array for 3x1")
        a = dff_array.dff_array(rows=3, columns=1)
        self.local_check(a)


OpenRamTest.run_tests(__name__)
