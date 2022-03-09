#!/usr/bin/env python3
"""
Run a regression test on a wordline_driver array
"""

from testutils import OpenRamTest
import debug


class ColumnDecoderTest(OpenRamTest):

    def run_commands(self, row_addr_size, col_addr_size):
        from modules import column_decoder

        decoder = column_decoder.ColumnDecoder(row_addr_size=row_addr_size, col_addr_size=col_addr_size)
        self.local_check(decoder)

    def test_no_decoder(self):
        debug.info(1, "Decoder with no column mux")
        self.run_commands(row_addr_size=6, col_addr_size=0)

    def test_1_2_decoder(self):
        debug.info(1, "Decoder with 1->2 column mux")
        self.run_commands(row_addr_size=6, col_addr_size=1)

    def test_2_4_decoder(self):
        debug.info(1, "Decoder with 2->4 column mux")
        self.run_commands(row_addr_size=6, col_addr_size=2)

    def test_3_8_decoder(self):
        debug.info(1, "Decoder with 3->8 column mux")
        self.run_commands(row_addr_size=6, col_addr_size=3)

        
OpenRamTest.run_tests(__name__)
