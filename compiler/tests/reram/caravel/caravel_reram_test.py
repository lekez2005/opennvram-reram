#!/usr/bin/env python3
import os
import sys
from unittest import skipIf

openram_home = os.environ.get("OPENRAM_HOME")
assert os.path.exists(openram_home), "OPENRAM_HOME must be set"
reram_dir = os.path.abspath(os.path.join(openram_home, "tests", "reram"))

assert os.path.exists(reram_dir), ""
sys.path.insert(0, reram_dir)

from reram_test_base import ReRamTestBase

generate_reram_gds = False
# This toggle exists to speed up layout generation during development
# should never be off: There may be power shorts if off
add_internal_grid = True
skip_ram_lvs = False


class ReRamTest(ReRamTestBase):

    @skipIf(False, "Skipping reram_wrapper")
    def test_1_reram_wrapper(self):
        from reram_wrapper import ReRamWrapper
        a = ReRamWrapper()
        if not skip_ram_lvs:
            self.local_check(a)

    @skipIf(False, "Skipping Caravel Wrapper generation")
    def test_2_caravel_caravel(self):
        from globals import OPTS
        OPTS.add_internal_grid = add_internal_grid
        from caravel.caravel_wrapper import CaravelWrapper
        a = CaravelWrapper()

        if not skip_ram_lvs:
            import verify
            self.local_drc_check(a)
            self.assertTrue(verify.run_lvs(a.name, a.lvs_gds_file, a.get_lvs_spice_file()) == 0)

    def test_0_generate_srams(self):
        from reram_wrapper import sram_configs
        from base.design import METAL4
        from base.utils import round_to_grid as round_
        created_modules = []
        for config in sram_configs:
            self.setUp()
            self.debug.info(2, "Spice file: %s", config.spice_file)
            self.debug.info(2, "GDS file: %s", config.gds_file)

            if os.path.exists(config.gds_file) and not generate_reram_gds:
                continue
            if config.module_name in created_modules:
                continue
            a = self.create_class_from_opts("sram_class", word_size=config.word_size,
                                            num_words=config.num_words,
                                            words_per_row=config.words_per_row,
                                            num_banks=config.num_banks,
                                            name=config.module_name,
                                            add_power_grid=True)
            # copy m4 pins to top level
            for pin_name in ["vdd", "gnd"]:
                for bank in a.bank_insts:
                    # only select pins that are at least as low as DATA[0]
                    data_pin = bank.get_pin("DATA[0]")
                    reference_y = round_(data_pin.by())
                    for pin in bank.get_pins(pin_name):
                        if not pin.layer == METAL4:
                            continue
                        if round_(pin.by()) <= reference_y:
                            a.add_layout_pin(pin_name, pin.layer, pin.ll(), pin.width(), pin.height())

            created_modules.append(config.module_name)

            if not skip_ram_lvs:
                self.local_check(a)

            a.sp_write(config.spice_file)
            a.gds_write(config.gds_file)


ReRamTest.run_tests(__name__)
