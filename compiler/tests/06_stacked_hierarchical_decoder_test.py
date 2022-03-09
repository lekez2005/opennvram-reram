#!/usr/bin/env python3
"""
Run a regression test on a stacked hierarchical decoder.
"""

from testutils import OpenRamTest


class StackedHierarchicalDecoderTest(OpenRamTest):
    def test_all_row_decoders(self):
        from globals import OPTS
        from modules.stacked_hierarchical_decoder \
            import stacked_hierarchical_decoder

        OPTS.decoder_flops = True
        for row in [32, 64, 128, 256, 512]:
            decoder = stacked_hierarchical_decoder(row)
            self.local_check(decoder)


StackedHierarchicalDecoderTest.run_tests(__name__)
