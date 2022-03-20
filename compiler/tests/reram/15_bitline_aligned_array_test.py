#!/usr/bin/env python3
"""
Run a regression test for peripherals vertically aligned to the bitcell array
"""

from reram_test_base import ReRamTestBase


class BitlineAlignedArrayTest(ReRamTestBase):

    # def test_sense_amp_array(self):
    #     self.debug.info(1, "Testing 2 words per row sense amp")
    #     a = self.create_class_from_opts("sense_amp_array", columns=32, word_size=32)
    #     self.local_check(a)
    #
    def test_write_driver_array(self):
        self.debug.info(1, "Testing 2 words per row write driver")
        a = self.create_class_from_opts("write_driver_array", columns=32, word_size=16)
        self.local_check(a)
    #
    # def test_flop_array(self):
    #     self.debug.info(1, "Testing 2 words per row flop array")
    #     a = self.create_class_from_opts("ms_flop_array", columns=32, word_size=32)
    #     self.local_check(a)

    # def test_tri_state_array(self):
    #     self.debug.info(1, "Testing 2 words per row tri state array")
    #     a = self.create_class_from_opts("tri_gate_array", columns=32, word_size=32)
    #     self.local_check(a)

    # def test_precharge_array(self):
    #     self.debug.info(1, "Testing precharge array")
    #     a = self.create_class_from_opts("precharge_array", columns=32, size=8)
    #     self.local_check(a)
    #
    # def test_column_mux_array(self):
    #     from globals import OPTS
    #     OPTS.mirror_bitcell_y_axis = True
    #     OPTS.symmetric_bitcell = False
    #
    #     self.debug.info(1, "Testing 2 words per row column mux array")
    #     a = self.create_class_from_opts("column_mux_array", columns=64, word_size=16)
    #     self.local_check(a)
    #
    # def test_flop_buffer(self):
    #     from globals import OPTS
    #     from modules.flop_buffer import FlopBuffer
    #     self.debug.info(1, "Testing flop buffer")
    #     a = FlopBuffer(OPTS.control_flop, OPTS.control_flop_buffers)
    #     self.local_check(a)
    #
    # def test_bitcell_array(self):
    #     self.debug.info(1, "Testing bitcell array")
    #     from modules.logic_buffer import LogicBuffer
    #     a = LogicBuffer(buffer_stages=[4.71, 14.6, 20], logic="pnand2", height=5,
    #                     align_bitcell=True, route_inputs=False)
    #     # a = self.create_class_from_opts("bitcell_array", cols=32, rows=32)
    #     self.local_check(a)


BitlineAlignedArrayTest.run_tests(__name__)
