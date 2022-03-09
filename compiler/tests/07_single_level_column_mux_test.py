#!/usr/bin/env python3
"""
Run a regression test on a single transistor column_mux.
"""

from testutils import OpenRamTest
import debug


class SingleLevelColumnMuxTest(OpenRamTest):

    def runTest(self):
        from modules.single_level_column_mux import single_level_column_mux
        
        debug.info(1, "8x ptx single level column mux")
        a = single_level_column_mux(tx_size=8)
        self.local_check(a)


OpenRamTest.run_tests(__name__)
