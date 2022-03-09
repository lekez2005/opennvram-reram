#!/usr/bin/env python3
"""
Run a regression test on a 2 bank SRAM
"""

from testutils import OpenRamTest
import debug


class Sram2BankTest(OpenRamTest):

    def runTest(self):
        import sram

        debug.info(1, "Two bank, no column mux with control logic")
        a = sram.sram(word_size=32, num_words=64, num_banks=2, name="sram1")
        self.local_check(a, final_verification=True)

        debug.info(1, "Two bank two way column mux with control logic")
        a = sram.sram(word_size=32, num_words=128, num_banks=2, name="sram2")
        self.local_check(a, final_verification=True)

        debug.info(1, "Two bank, four way column mux with control logic")
        a = sram.sram(word_size=32, num_words=256, num_banks=2, name="sram3")
        self.local_check(a, final_verification=True)

        # debug.info(1, "Two bank, eight way column mux with control logic")
        # a = sram.sram(word_size=2, num_words=256 num_banks=2, name="sram4")
        # self.local_check(a, final_verification=True)


OpenRamTest.run_tests(__name__)
