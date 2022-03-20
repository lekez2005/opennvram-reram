import os

from characterizer import stimuli, OPTS
from modules.reram.reram import ReRam


class ReramSpiceDut(stimuli):

    def generate_constant_voltages(self):
        self.gen_constant("vdd_wordline", OPTS.vdd_wordline, gnd_node="gnd")
        if OPTS.separate_vdd_write:
            self.gen_constant("vdd_write_bl", OPTS.vdd_write_bl, gnd_node="gnd")
            self.gen_constant("vdd_write_br", OPTS.vdd_write_br, gnd_node="gnd")
        else:
            self.gen_constant("vdd_write", OPTS.vdd_write, gnd_node="gnd")
        self.gen_constant("vref", OPTS.sense_amp_vref)
        self.gen_constant("vclamp", OPTS.sense_amp_vclamp)
        self.gen_constant("vclampp", OPTS.sense_amp_vclampp)

    def instantiate_sram(self, sram: ReRam):
        super().instantiate_sram(sram)
        self.generate_constant_voltages()

    def write_include(self, circuit):
        super().write_include(circuit)
        reram_device_file = os.path.join(OPTS.openram_tech, "sp_lib",
                                         "sky130_fd_pr__reram_reram_cell.sp")
        self.sf.write(f'.include "{reram_device_file}"\n')
        reram_model_file = os.path.join(OPTS.openram_tech, "sp_lib",
                                        "reram_cell_model.va")
        self.sf.write(f".hdl {reram_model_file}\n")
