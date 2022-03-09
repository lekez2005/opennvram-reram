#!/usr/bin/env python3

from bank_test_base import BankTestBase
from testutils import OpenRamTest


class BankTest(BankTestBase, OpenRamTest):
    pass


BankTest.run_tests(__name__)
