#!/usr/bin/env python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from testutils import OpenRamTest
else:
    class OpenRamTest:
        pass


class SramTestBase(OpenRamTest):
    errors = []
    error_message = ""

    def get_sram_class(self):
        sram_class = self.load_class_from_opts("sram_class")
        return sram_class

    def sweep_all(self, rows=None, cols=None, words_per_row=None, default_row=64,
                  default_col=64, num_banks=1):

        from tests.bank_test_base import patch_print_error, catch_errors, print_error, BankTestBase
        patch_print_error(self)

        sram_class = self.get_sram_class()

        for row, col, words_per_row_ in BankTestBase.create_trials(rows, cols, words_per_row,
                                                                   default_col, default_row):
            try:
                self.create_and_test_sram(sram_class, row, col, words_per_row_, num_banks)
            except Exception:
                catch_errors(self, row, col, words_per_row_)

        for error in self.errors:
            print_error(error)

    def create_and_test_sram(self, sram_class, num_rows, num_cols, words_per_row, num_banks):
        self.debug.info(1, "Test {} row = {} col = {} words_per_row = {} num_banks = {}".
                        format(sram_class.__name__, num_rows, num_cols, words_per_row, num_banks))
        word_size = int(num_cols / words_per_row)
        num_words = num_rows * words_per_row * num_banks
        self.reset()
        a = sram_class(word_size=word_size, num_words=num_words, words_per_row=words_per_row,
                       num_banks=num_banks, name="sram1", add_power_grid=True)

        self.local_check(a)

    # def test_sweep_all(self):
    #     self.sweep_all(cols=[], rows=[16], words_per_row=1, default_col=16, num_banks=1)
    #     # self.sweep_all(cols=[], rows=[32], words_per_row=1, default_col=32, num_banks=1)
    #     # self.sweep_all(cols=[], rows=[64], words_per_row=1, default_col=64, num_banks=1)
    #     # self.sweep_all(cols=[], rows=[64], words_per_row=2, default_col=64, num_banks=1)
    #     # self.sweep_all()

    def test_one_bank(self):
        sram_class = self.get_sram_class()
        from globals import OPTS
        OPTS.run_optimizations = False
        self.create_and_test_sram(sram_class, 32, 16, words_per_row=2, num_banks=1)

    # def test_two_dependent_banks(self):
    #     from globals import OPTS
    #     OPTS.independent_banks = False
    #     sram_class = self.get_sram_class()
    #     for words_per_row in [1, 2, 4, 8]:
    #         self.create_and_test_sram(sram_class, 64, 64, words_per_row=words_per_row, num_banks=2)
    #
    # def test_two_independent_banks(self):
    #     from globals import OPTS
    #     OPTS.independent_banks = True
    #     sram_class = self.get_sram_class()
    #     for words_per_row in [1, 2, 4, 8]:
    #         self.create_and_test_sram(sram_class, 64, 64, words_per_row=words_per_row, num_banks=2)
