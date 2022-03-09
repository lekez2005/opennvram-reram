#!/usr/bin/env python3
"""
Run a regression test for peripherals vertically aligned to the bitcell array
"""

from testutils import OpenRamTest
import debug


class BitlineAlignedArrayTest(OpenRamTest):

    def test_sense_amp_array(self):
        debug.info(1, "Testing 2 words per row sense amp")
        a = self.create_class_from_opts("sense_amp_array", columns=128, word_size=64)
        self.local_check(a)

    def test_write_driver_array(self):
        debug.info(1, "Testing 2 words per row write driver")
        a = self.create_class_from_opts("write_driver_array", columns=128, word_size=64)
        self.local_check(a)

    def test_flop_array(self):
        debug.info(1, "Testing 2 words per row flop array")
        a = self.create_class_from_opts("ms_flop_array", columns=32, word_size=16)
        self.local_check(a)

    def test_tri_state_array(self):
        debug.info(1, "Testing 2 words per row tri state array")
        a = self.create_class_from_opts("tri_gate_array", columns=32, word_size=16)
        self.local_check(a)

    def test_precharge_array(self):
        debug.info(1, "Testing precharge array")
        a = self.create_class_from_opts("precharge_array", columns=32, size=8)
        self.local_check(a)

    def test_column_mux_array(self):
        from globals import OPTS
        OPTS.mirror_bitcell_y_axis = True
        OPTS.symmetric_bitcell = False

        debug.info(1, "Testing 2 words per row column mux array")
        a = self.create_class_from_opts("column_mux_array", columns=64, word_size=16)
        self.local_check(a)

    def test_bitcell_array(self):
        debug.info(1, "Testing bitcell array")
        a = self.create_class_from_opts("bitcell_array", cols=32, rows=64)
        self.local_check(a)


BitlineAlignedArrayTest.run_tests(__name__)
