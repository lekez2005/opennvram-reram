#!/usr/bin/env python3
"""
Run a regression test on a tri_gate_array.
"""

from testutils import OpenRamTest
import debug


class TriGateArrayTest(OpenRamTest):

    def runTest(self):

        debug.info(1, "Testing tri_gate_array for columns=8, word_size=8")
        a = self.create_class_from_opts("tri_gate_array", columns=8, word_size=8)
        self.local_check(a)

        debug.info(1, "Testing tri_gate_array for columns=16, word_size=8")
        a = self.create_class_from_opts("tri_gate_array", columns=16, word_size=8)
        self.local_check(a)


OpenRamTest.run_tests(__name__)
