#!/usr/bin/env python3
"""
Run a regression test on a single transistor column_mux.
"""

from testutils import OpenRamTest


class TgateColMuxPgateTest(OpenRamTest):

    def runTest(self):
        from modules.tgate_column_mux_pgate import tgate_column_mux_pgate

        a = tgate_column_mux_pgate()

        self.debug.info(1, "Created tgate_column_mux_pgate nmos "
                           "size = %.3g pmos size = %.3g", a.tgate_size, a.tgate_pmos_size)

        self.local_check(a)


OpenRamTest.run_tests(__name__)
