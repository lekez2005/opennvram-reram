#!/usr/bin/env python3
"""
Run a regression test on a hierarchical_decoder.
"""

from testutils import OpenRamTest
from row_decoder_base_test import RowDecoderBase


class RowDecoderTest(RowDecoderBase, OpenRamTest):
    pass


RowDecoderTest.run_tests(__name__)
