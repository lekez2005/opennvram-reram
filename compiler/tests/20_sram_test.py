#!/usr/bin/env python3

from sram_test_base import SramTestBase
from testutils import OpenRamTest


class SramTest(SramTestBase, OpenRamTest):
    pass


SramTest.run_tests(__name__)
