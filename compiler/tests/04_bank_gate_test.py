#!/usr/bin/env python3
"""
Run a regression test on a wordline_driver array
"""

from testutils import OpenRamTest
OpenRamTest.initialize_tests()
import debug
from modules.bank_gate import BankGate
from modules.bank_gate import ControlGate


class BankGateTest(OpenRamTest):

    def test_bank_gate(self):
        debug.info(1, "Checking bank gate")

        control_gates = [
            ControlGate("s_en"),
            ControlGate("clk", route_complement=True),
            ControlGate("w_en")
        ]

        gate = BankGate(control_gates)
        self.local_check(gate)

    def test_left_output(self):
        debug.info(1, "Checking bank gate")

        control_gates = [
            ControlGate("s_en"),
            ControlGate("clk", route_complement=True, output_dir="left"),
            ControlGate("sig2", route_complement=False, output_dir="left"),
            ControlGate("w_en")
        ]

        gate = BankGate(control_gates)
        self.local_check(gate)

        
OpenRamTest.run_tests(__name__)
