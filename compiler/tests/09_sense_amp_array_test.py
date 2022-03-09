#!/usr/bin/env python3
"""
Run a regression test on a sense amp array
"""

from testutils import OpenRamTest
import debug


class SenseAmpTest(OpenRamTest):

    def runTest(self):
        from globals import OPTS

        module = __import__(OPTS.sense_amp_array)
        mod_class = getattr(module, OPTS.sense_amp_array)

        debug.info(1, "Sense amp class name is {}".format(OPTS.sense_amp_array))

        debug.info(2, "Testing sense_amp_array for word_size=8, words_per_row=1")
        a = mod_class(word_size=64, words_per_row=1)
        self.local_check(a)

        debug.info(2, "Testing sense_amp_array for word_size=4, words_per_row=2")
        a = mod_class(word_size=4, words_per_row=2)
        self.local_check(a)

        debug.info(2, "Testing sense_amp_array for word_size=4, words_per_row=4")
        a = mod_class(word_size=4, words_per_row=4)
        self.local_check(a)
        

OpenRamTest.run_tests(__name__)
