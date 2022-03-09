#!/usr/bin/env python3
"""
Run a regression test on a dff_array.
"""

from testutils import OpenRamTest
import debug


class MsFlopArrayTest(OpenRamTest):

    def runTest(self):
        from modules import ms_flop_array

        debug.info(2, "Testing ms_flop_array for columns=64, word_size=64 aligned to bitcell")
        a = ms_flop_array.ms_flop_array(columns=128, word_size=128, align_bitcell=True)
        self.local_check(a)

        debug.info(2, "Testing ms_flop_array for columns=64, word_size=32 aligned to bitcell")
        a = ms_flop_array.ms_flop_array(columns=128, word_size=64, align_bitcell=True)
        self.local_check(a)

        debug.info(2, "Testing ms_flop_array for columns=8, word_size=8")
        a = ms_flop_array.ms_flop_array(columns=8, word_size=8)
        self.local_check(a)

        debug.info(2, "Testing ms_flop_array for columns=16, word_size=8")
        a = ms_flop_array.ms_flop_array(columns=16, word_size=8)
        self.local_check(a)

        
OpenRamTest.run_tests(__name__)
