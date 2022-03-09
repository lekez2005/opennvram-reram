#!/usr/bin/env python3
"""
Run a regression test on a dff_array.
"""

from testutils import OpenRamTest
import debug


class MsFlopArrayHorizontalTest(OpenRamTest):

    def runTest(self):
        from modules import ms_flop_array_horizontal

        debug.info(2, "Testing ms_flop_array for columns=8, word_size=8")
        a = ms_flop_array_horizontal.ms_flop_array_horizontal(columns=8, word_size=8,
                                                              align_bitcell=True)
        self.local_check(a)

        debug.info(2, "Testing ms_flop_array for columns=16, word_size=8")
        a = ms_flop_array_horizontal.ms_flop_array_horizontal(columns=16, word_size=8,
                                                              align_bitcell=True)
        self.local_check(a)


OpenRamTest.run_tests(__name__)
