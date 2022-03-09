#!/usr/bin/env python3
"""
Run a regression test on various srams
"""

from testutils import OpenRamTest
import debug


class MultiBankTest(OpenRamTest):

    def runTest(self):
        from modules import bank

        debug.info(1, "No column mux")
        a = bank.bank(word_size=32, num_words=16, words_per_row=1, num_banks=2, name="bank1")
        self.local_check(a)

        debug.info(1, "Two way column mux")
        a = bank.bank(word_size=32, num_words=32, words_per_row=2, num_banks=2, name="bank2")
        self.local_check(a)

        debug.info(1, "Four way column mux")
        a = bank.bank(word_size=32, num_words=64, words_per_row=4, num_banks=2, name="bank3")
        self.local_check(a)

        debug.info(1, "Four way column mux 32 rows")
        a = bank.bank(word_size=32, num_words=64, words_per_row=2, num_banks=2, name="bank4")
        self.local_check(a)

        debug.info(1, "Eight way column mux")
        a = bank.bank(word_size=32, num_words=128, words_per_row=8, num_banks=2, name="bank5")
        self.local_check(a)
        

OpenRamTest.run_tests(__name__)
