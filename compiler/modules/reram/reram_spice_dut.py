import os

from characterizer import stimuli, OPTS
from modules.reram.reram import ReRam


class ReramSpiceDut(stimuli):

    def instantiate_sram(self, sram: ReRam):
        super().instantiate_sram(sram)

        self.gen_constant("vdd_wordline", OPTS.vdd_wordline, gnd_node="gnd")
        self.gen_constant("vdd_write", OPTS.vdd_write, gnd_node="gnd")
        self.gen_constant("vref", OPTS.sense_amp_vref)
        self.gen_constant("vclamp", OPTS.sense_amp_vclamp)
        self.gen_constant("vclampp", OPTS.sense_amp_vclampp)

    def write_include(self, circuit):
        super().write_include(circuit)
        reram_model_file = os.path.join(OPTS.openram_tech, "sp_lib",
                                        "reram_cell_model.va")
        self.sf.write(f".hdl {reram_model_file}\n")
