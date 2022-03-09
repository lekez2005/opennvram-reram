from characterizer import SpiceCharacterizer
from characterizer.net_probes.sram_probe import SramProbe
from globals import OPTS
from modules.reram.reram_spice_dut import ReramSpiceDut


class ReramProbe(SramProbe):
    def probe_address(self, address, pin_name="q"):
        probe_node = OPTS.state_probe_node
        super().probe_address(address, pin_name=probe_node)

    def get_sense_amp_internal_nets(self):
        return ["dout", "vdata", "bl"]

    def get_bitcell_current_nets(self):
        return ["be"]


class ReramSpiceCharacterizer(SpiceCharacterizer):
    def create_dut(self):
        stim = ReramSpiceDut(self.sf, self.corner)
        stim.words_per_row = self.sram.words_per_row
        return stim

    def write_ic(self, ic, col_node, col_voltage):
        return
        # vdd = self.vdd_voltage
        # if col_voltage > 0.5 * vdd:
        #     col_voltage = OPTS.min_filament_thickness
        # else:
        #     col_voltage = OPTS.max_filament_thickness
        # ic.write(".ic V({})={} \n".format(col_node, col_voltage))

    def create_probe(self):
        self.probe = ReramProbe(self.sram, OPTS.pex_spice)
