#!/usr/bin/env python3
"""
Run a regression test on a wordline_driver array
"""

from testutils import OpenRamTest
import debug


class SignalGateTest(OpenRamTest):

    def run_commands(self, buffer_stages):
        from modules import signal_gate
        gate = signal_gate.SignalGate(buffer_stages)
        self.local_check(gate)

    def test_no_buffer(self):
        debug.info(1, "Checking without buffer")
        self.run_commands([1])

    def test_with_odd_buffers(self):
        debug.info(1, "Checking with two buffers")
        self.run_commands([1, 2, 4])

    def test_with_even_buffers(self):
        debug.info(1, "Checking with two buffers")
        self.run_commands([1, 2, 4, 8])

        
OpenRamTest.run_tests(__name__)
