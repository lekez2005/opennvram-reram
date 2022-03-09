#!/usr/bin/env python3
"""
Run regression tests on a parameterized nand 2.  This module doesn't
generate a multi_finger 2-input nand gate.  It generates only a minimum
size 2-input nand gate.
"""

from testutils import OpenRamTest
import debug


class PGateTapTest(OpenRamTest):

    def test_pinv8(self):
        from pgates.pinv import pinv
        from pgates.pgate_tap import pgate_tap

        debug.info(2, "Checking wrapped inverter body tap")
        inv = pinv(size=8, contact_pwell=False, contact_nwell=False)
        body_tap = pgate_tap(inv)
        wrapped_cell = pgate_tap.wrap_pgate_tap(inv, body_tap)
        self.local_check(wrapped_cell)

    def test_pnand2(self):
        from pgates.pnand2 import pnand2
        from pgates.pgate_tap import pgate_tap

        debug.info(2, "Checking wrapped inverter body tap")
        nand = pnand2(size=1, contact_pwell=False, contact_nwell=False)
        body_tap = pgate_tap(nand)
        wrapped_cell = pgate_tap.wrap_pgate_tap(nand, body_tap)
        self.local_check(wrapped_cell)


OpenRamTest.run_tests(__name__)
