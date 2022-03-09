#!/usr/bin/env python3
"""
Run a regression test on a basic array
"""

from testutils import OpenRamTest
import debug


class ArrayTest(OpenRamTest):

    def runTest(self):
        from modules import bitcell_array

        debug.info(2, "Testing 4x4 array for 6t_cell")
        a = bitcell_array.bitcell_array(name="bitcell_array", cols=4, rows=4)
        self.local_check(a)


OpenRamTest.run_tests(__name__)
