#!/usr/bin/env python3
"""
Run a regression test on a logic_buffers module.
"""
from types import SimpleNamespace

from reram_test_base import ReRamTestBase


class ReRamControlBuffersTest(ReRamTestBase):

    def test_control_buffers(self):
        from globals import OPTS
        from modules.reram.reram_control_buffers import ReRamControlBuffers
        OPTS.num_banks = 1
        bank = SimpleNamespace(is_left_bank=False, words_per_row=1)

        dut = ReRamControlBuffers(bank=bank)
        self.local_check(dut)


ReRamControlBuffersTest.run_tests(__name__)
