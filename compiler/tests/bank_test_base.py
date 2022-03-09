#!/usr/bin/env python3
import traceback
from importlib import reload
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from testutils import OpenRamTest
else:
    class OpenRamTest:
        pass


def patch_print_error(self):
    import debug
    original_func = debug.error

    def patch_func(message, return_value=-1, *args):
        if return_value == 0:
            return
        self.error_message = message % args
        original_func(message, return_value, *args)

    debug.error = patch_func


def catch_errors(self, row, col, words_per_row_):
    error_message = self.error_message or traceback.format_exc()
    self.errors.append((row, col, words_per_row_, error_message))
    self.error_message = ""
    print_error(self.errors[-1])


def print_error(error):
    import debug
    row, col, words_per_row, error = error
    debug.warning("Fail: wpr= %d row = %d col = %d \n %s ",
                  words_per_row, row, col, str(error))


class BankTestBase(OpenRamTest):
    errors = []
    error_message = ""

    def local_check(self, a, final_verification=False):
        if hasattr(a.wordline_driver, "add_body_taps"):
            a.wordline_driver.add_body_taps()
        super().local_check(a, final_verification)

    @staticmethod
    def get_bank_class():
        from globals import OPTS
        if hasattr(OPTS, "bank_class"):
            from base.design import design
            return design.import_mod_class_from_str(OPTS.bank_class), {}

        from modules.baseline_bank import BaselineBank
        bank_class = BaselineBank
        return bank_class, {}

    @staticmethod
    def create_trials(rows, cols, words_per_row, default_col, default_row):
        from testutils import OpenRamTest as OpenRamTest_
        if rows is None:
            rows = [16, 32, 64, 128, 256]
        if cols is None:
            cols = [32, 64, 128, 256]

        trials = []
        col = default_col
        for row in rows:
            for words_per_row_ in OpenRamTest_.get_words_per_row(col, words_per_row):
                trials.append((row, col, words_per_row_))
        row = default_row
        for col in cols:
            if col == default_col:
                continue
            for words_per_row_ in OpenRamTest_.get_words_per_row(col, words_per_row):
                trials.append((row, col, words_per_row_))
        return trials

    def sweep_all(self, rows=None, cols=None, words_per_row=None, default_row=64, default_col=64):
        patch_print_error(self)

        bank_class, kwargs = self.get_bank_class()
        trials = self.create_trials(rows, cols, words_per_row, default_col, default_row)

        for row, col, words_per_row_ in trials:
            try:
                self.reset()
                self.debug.info(1, "Test %s single bank row = %d col = %d wpr = %d",
                                bank_class.__name__, row, col, words_per_row_)
                word_size = int(col / words_per_row_)
                num_words = row * words_per_row_
                a = bank_class(word_size=word_size, num_words=num_words,
                               words_per_row=words_per_row_, name="bank1", **kwargs)
                self.local_check(a)
            except KeyboardInterrupt:
                break
            except Exception as ex:
                catch_errors(self, row, col, words_per_row_)

        for error in self.errors:
            print_error(error)

    # def test_sweep(self):
    #     self.sweep_all(cols=[256], rows=[32], words_per_row=1, default_col=256)
    #     # self.sweep_all()

    def test_chip_sel(self):
        """Test for chip sel: Two independent banks"""
        from globals import OPTS
        bank_class, kwargs = self.get_bank_class()
        OPTS.route_control_signals_left = True
        OPTS.independent_banks = True
        OPTS.num_banks = 1
        OPTS.run_optimizations = True
        a = bank_class(word_size=16, num_words=16, words_per_row=1,
                       name="bank1", **kwargs)
        self.local_check(a)

    # def test_intra_array_control_signals_rails(self):
    #     """Test for control rails within peripherals arrays but not centralized
    #         (closest to driver pin)"""
    #     from globals import OPTS
    #     bank_class, kwargs = self.get_bank_class()
    #     OPTS.route_control_signals_left = False
    #     OPTS.num_banks = 1
    #     OPTS.centralize_control_signals = False
    #     a = bank_class(word_size=64, num_words=64, words_per_row=1,
    #                    name="bank1", **kwargs)
    #     self.local_check(a)
    #
    # def test_intra_array_centralize_control_signals_rails(self):
    #     """Test for when control rails are centralized in between bitcell array"""
    #     from globals import OPTS
    #     bank_class, kwargs = self.get_bank_class()
    #     OPTS.route_control_signals_left = False
    #     OPTS.num_banks = 1
    #     OPTS.centralize_control_signals = True
    #     a = bank_class(word_size=64, num_words=64, words_per_row=1,
    #                    name="bank1", **kwargs)
    #     self.local_check(a)
    #
    # def test_intra_array_wide_control_buffers(self):
    #     """Test for when control buffers width is greater than bitcell array width"""
    #     from globals import OPTS
    #     bank_class, kwargs = self.get_bank_class()
    #     OPTS.route_control_signals_left = False
    #     OPTS.num_banks = 1
    #     OPTS.control_buffers_num_rows = 1
    #     OPTS.centralize_control_signals = False
    #     a = bank_class(word_size=16, num_words=64, words_per_row=1,
    #                    name="bank1", **kwargs)
    #     self.assertTrue(a.control_buffers.width > a.bitcell_array.width,
    #                     "Adjust word size such that control buffers is wider than bitcell array")
    #     self.local_check(a)
