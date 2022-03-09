#!/usr/bin/env python3

from reram_test_base import ReRamTestBase
from bank_test_base import BankTestBase


class ReRanBankTest(BankTestBase, ReRamTestBase):
    pass


ReRanBankTest.run_tests(__name__)
