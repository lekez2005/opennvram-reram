#!/usr/bin/env python3
"""
Run a regression test on a wordline_driver array
"""

from testutils import OpenRamTest
import debug


class WordlineDriverTest(OpenRamTest):

    def run_commands(self, rows, cols):

        import tech
        from modules import wordline_driver

        tech.drc_exceptions["wordline_driver"] = tech.drc_exceptions["latchup"] + tech.drc_exceptions["min_nwell"]

        tx = wordline_driver.wordline_driver(rows=rows, no_cols=cols)
        self.local_drc_check(tx)

    def test_no_buffer(self):
        debug.info(1, "Checking driver without buffer")
        self.run_commands(8, 8)

    def test_with_buffer(self):
        debug.info(1, "Checking driver with buffer")
        self.run_commands(8, 32)

        
OpenRamTest.run_tests(__name__)
