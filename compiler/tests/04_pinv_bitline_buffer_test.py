#!/usr/bin/env python3
"""
Run regression tests on a parameterized inverter
"""
from unittest import skipIf

from testutils import OpenRamTest
import debug


class PinvBitlineBufferTest(OpenRamTest):

    @skipIf(False, "skip switch")
    def test_small_size(self):
        from pgates.pinv_bitline_buffer import pinv_bitine_buffer

        debug.info(2, "Checking 1x size inverter")
        tx = pinv_bitine_buffer(size=1, contact_pwell=False, contact_nwell=False)
        self.local_check(tx)

    @skipIf(False, "skip switch")
    def test_large_size(self):
        from pgates.pinv_bitline_buffer import pinv_bitine_buffer

        debug.info(2, "Checking 1x size inverter")
        tx = pinv_bitine_buffer(size=6, contact_pwell=False, contact_nwell=False)
        self.local_check(tx)


OpenRamTest.run_tests(__name__)
