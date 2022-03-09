#!/usr/bin/env python3
"Run a regression test on a basic parameterized transistors"

from testutils import OpenRamTest
import debug


class PtxTest(OpenRamTest):

    def test_ptx_1finger_nmos(self):
        debug.info(2, "Checking min size NMOS with 1 finger")
        self.run_tx(tx_type="nmos")

    def test_ptx_1finger_pmos(self):
        debug.info(2, "Checking min size PMOS with 1 finger")
        self.run_tx(tx_type="pmos")

    def test_ptx_3finger_nmos(self):
        debug.info(2, "Checking three fingers NMOS")
        self.run_tx(tx_type="nmos", mults=3)

    def test_ptx_3finger_indep_nmos(self):
        debug.info(2, "Checking three fingers independent poly NMOS")
        self.run_tx(tx_type="nmos", mults=3, independent_poly=True)

    def test_ptx_3finger_pmos(self):
        debug.info(2, "Checking three fingers PMOS")
        self.run_tx(tx_type="pmos", mults=3)

    def test_nmos_4finger_active_poly(self):
        debug.info(2, "Checking four fingers NMOS, connect active and poly")
        self.run_tx(tx_type="nmos", mults=4, width=2, connect_active=True, connect_poly=True)

    def test_pmos_4finger_active_poly(self):
        debug.info(2, "Checking four fingers PMOS, connect active and poly")
        self.run_tx(tx_type="pmos", mults=4, width=2, connect_active=True, connect_poly=True)

    def test_ptx_wide_1finger_nmos(self):
        debug.info(2, "Checking min size NMOS with 1 finger")
        self.run_tx(tx_type="nmos", width=5)

    def test_ptx_wide_4finger_nmos(self):
        debug.info(2, "Checking min size NMOS with 1 finger")
        self.run_tx(tx_type="nmos", width=5, mults=4)

    def test_ptx_wide_4finger_connect_nmos(self):
        debug.info(2, "Checking min size NMOS with 1 finger")
        self.run_tx(tx_type="nmos", width=5, mults=4, connect_poly=True, connect_active=True)

    def run_tx(self, tx_type="nmos", mults=1, width=1, connect_active=False, connect_poly=False, **kwargs):
        from pgates import ptx
        import tech
        fet = ptx.ptx(width=width*tech.drc["minwidth_tx"],
                      mults=mults,
                      tx_type=tx_type,
                      connect_active=connect_active,
                      connect_poly=connect_poly, **kwargs)
        self.local_drc_check(fet)


OpenRamTest.run_tests(__name__)
