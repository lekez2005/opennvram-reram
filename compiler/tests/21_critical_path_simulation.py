#!/usr/bin/env python3
import argparse
import sys
from collections import namedtuple
from unittest import skipUnless

from testutils import OpenRamTest

PATH_DECODER = "decoder"
PATH_PRECHARGE = "precharge"
PATH_ALL = "all"

parser = argparse.ArgumentParser()
parser.add_argument("-s", "--schematic", action="store_true",
                    help="Schematic or Extracted simulation")
parser.add_argument("-o", "--optimize", action="store_true", default=True,
                    help="Run logic effort based buffer optimizations")
parser.add_argument("--run_drc_lvs", action="store_true", help="Run DRC and LVS for each module")
parser.add_argument("--path", default=PATH_ALL, help="Path to evaluate", choices=[
    PATH_ALL,
    PATH_PRECHARGE,
    PATH_DECODER
])
parser.add_argument("--config", default="mram/config_shared_baseline_{}",
                    help="Config file relative to working directory")
parser.add_argument("--num_rows", default=512, type=int)
parser.add_argument("--num_cols", default=256, type=int)
parser.add_argument("--word_size", default=32, type=int)

first_arg = sys.argv[0]
options, other_args = parser.parse_known_args()
# restore args for further OpenRAM options processing
sys.argv = [first_arg] + other_args


class CriticalPathSimulation(OpenRamTest):
    config_template = options.config
    control_buffer = None

    def setUp(self):
        super().setUp()

        from globals import OPTS
        from tech import delay_strategy_class

        BankTuple = namedtuple("Bank", "num_rows num_cols")
        bank = BankTuple(num_rows=options.num_rows, num_cols=options.num_cols)
        if hasattr(OPTS, "configure_modules"):
            getattr(OPTS, "configure_modules")(bank, OPTS)
        if options.optimize:
            self.delay_optimizer = delay_strategy_class()(bank)

    @skipUnless(options.path == PATH_DECODER, "")
    def test_decoder(self):
        self.eval_decoder()

    @skipUnless(options.path == PATH_PRECHARGE, "")
    def test_precharge(self):
        self.eval_precharge()

    @skipUnless(options.path == PATH_ALL, "")
    def test_all(self):
        # first half of cycle: decoder, precharge, column mux
        self.eval_precharge()
        decoder_delay = self.eval_decoder()

    def eval_precharge(self):
        self.delay_optimizer.get_precharge_sizes()

    def eval_decoder(self):
        num_rows = options.num_rows
        self.debug.info(2, "Running simulation for {} row decoder".format(num_rows))

        return 0


if __name__ == "__main__":
    CriticalPathSimulation.run_tests(__name__)
