#!/usr/bin/env python3

from reram_test_base import ReRamTestBase
from sram_test_base import SramTestBase


class ReramTest(SramTestBase, ReRamTestBase):
    pass


ReramTest.run_tests(__name__)
