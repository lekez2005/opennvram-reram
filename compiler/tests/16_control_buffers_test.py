#!/usr/bin/env python3
"""
Run a regression test on a logic_buffers module.
"""
from types import SimpleNamespace

from testutils import OpenRamTest


class ControlBuffersTest(OpenRamTest):

    @staticmethod
    def make_buffers(bank):
        from globals import OPTS
        if hasattr(OPTS, "control_buffers_class"):
            return ControlBuffersTest.create_class_from_opts("control_buffers_class",
                                                             bank=bank)
        from modules.baseline_latched_control_buffers import LatchedControlBuffers
        return LatchedControlBuffers(bank=bank)

    def test_decoder_clk(self):
        """Test explicit decoder clock creation"""
        from globals import OPTS
        OPTS.num_banks = 1
        OPTS.create_decoder_clk = True

        bank = SimpleNamespace(is_left_bank=False, words_per_row=1)
        a = self.make_buffers(bank)
        self.local_check(a)

    def test_one_two_rows(self):
        from globals import OPTS
        OPTS.num_banks = 1
        OPTS.create_decoder_clk = True
        # test one row
        OPTS.control_buffers_num_rows = 1
        bank = SimpleNamespace(is_left_bank=False, words_per_row=1)
        a = self.make_buffers(bank)
        self.local_check(a)
        # test two rows
        OPTS.control_buffers_num_rows = 2
        bank = SimpleNamespace(is_left_bank=False, words_per_row=1)
        a = self.make_buffers(bank)
        self.local_check(a)

    def test_col_mux_precharge(self):
        """Test column mux and no column mux precharge:
         No precharge needed when there is no column mux since no risk of inadvertent writes"""
        from globals import OPTS
        OPTS.num_banks = 1
        bank = SimpleNamespace(is_left_bank=False, words_per_row=1)
        a = self.make_buffers(bank)
        self.assertTrue("pnand3" in a.precharge_buf.name, "Should use pnand3 for precharge when no col mux")
        self.local_check(a)

        bank = SimpleNamespace(is_left_bank=False, words_per_row=2)
        a = self.make_buffers(bank)
        self.assertTrue("pnand2" in a.precharge_buf.name, "Should use pnand2 for precharge when there is col mux")
        self.local_check(a)

    def test_two_bank_chip_sel(self):
        from globals import OPTS
        OPTS.independent_banks = True
        OPTS.num_banks = 2
        bank = SimpleNamespace(is_left_bank=False, words_per_row=1)
        a = self.make_buffers(bank)
        self.assertIn("chip_sel", a.get_input_pin_names(), "chip_sel is in input pins")
        self.assertIn("bank_sel", a.get_input_pin_names(), "bank_sel is in input pins")
        self.assertIn("decoder_clk", a.get_output_pin_names(), "decoder_clk is in output pins")
        self.local_check(a)


ControlBuffersTest.run_tests(__name__)
