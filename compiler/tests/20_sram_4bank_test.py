#!/usr/bin/env python3
"""
Run a regression test on a 4 bank SRAM
"""

from testutils import OpenRamTest
import debug


class Sram4BankTest(OpenRamTest):

    def runTest(self):
        import sram

        debug.info(1, "Four bank, no column mux with control logic")
        a = sram.sram(word_size=64, num_words=128, num_banks=4, name="sram1")
        self.local_check(a, final_verification=True)

        debug.info(1, "Four bank two way column mux with control logic")
        a = sram.sram(word_size=64, num_words=256, num_banks=4, name="sram2")
        self.local_check(a, final_verification=True)

        debug.info(1, "Four bank, four way column mux with control logic")
        a = sram.sram(word_size=64, num_words=512, num_banks=4, name="sram3")
        self.local_check(a, final_verification=True)

        # debug.info(1, "Four bank, eight way column mux with control logic")
        # a = sram.sram(word_size=2, num_words=256, num_banks=4, name="sram4")
        # self.local_check(a, final_verification=True)


OpenRamTest.run_tests(__name__)