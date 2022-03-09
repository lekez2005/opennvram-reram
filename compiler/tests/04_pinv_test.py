#!/usr/bin/env python3
"""
Run regression tests on a parameterized inverter
"""
from testutils import OpenRamTest


class PinvTest(OpenRamTest):

    def test_1x_pinv(self):
        import debug
        import tech
        from pgates import pinv

        debug.info(2, "Checking 1x size inverter")
        tx = pinv.pinv(size=1)
        self.local_check(tx)

        debug.info(2, "Checking 1x size without well contacts")
        tech.drc_exceptions["pinv"] = tech.drc_exceptions.get("latchup", [])
        tx = pinv.pinv(size=1, contact_nwell=False, contact_pwell=False)
        self.local_drc_check(tx)

        debug.info(2, "Checking 1x bitcell pitch matched")
        tech.drc_exceptions["pinv"] = (tech.drc_exceptions.get("latchup", []) +
                                       tech.drc_exceptions.get("min_nwell", []))
        tx = pinv.pinv(size=1, contact_nwell=False, contact_pwell=False, align_bitcell=True)
        self.local_drc_check(tx)

    def test_pinv_beta(self):
        import debug
        from pgates import pinv
        debug.info(2, "Checking 1x beta=3 size inverter")
        tx = pinv.pinv(size=1, beta=3)
        self.local_check(tx)

    def test_pinv_2x(self):
        import debug
        from pgates import pinv
        debug.info(2, "Checking 2x size inverter")
        tx = pinv.pinv(size=2)
        self.local_check(tx)

    def test_pinv_10x(self):
        import debug
        from pgates import pinv
        debug.info(2, "Checking 10x size inverter")
        tx = pinv.pinv(size=10)
        self.local_check(tx)


OpenRamTest.run_tests(__name__)
