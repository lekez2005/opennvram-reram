from globals import OPTS
from modules.control_buffers import ControlBuffers
from modules.logic_buffer import LogicBuffer
from pgates.pnand2 import pnand2


class LatchedControlBuffers(ControlBuffers):
    """
    Generate and buffer control signals using bank_sel, clk and read
    Assumes write if read_bar, bitline computation vs read difference is handled at decoder level
    Inputs:
        bank_sel, read, clk, sense_trig
    Define internal signal
        bank_sel_cbar = NAND(clk_bar, bank_sel)
    Outputs

        clk_buf:            bank_sel.clk
        precharge_en_bar:   and3(read, clk, bank_sel)
        write_en:           and3(read_bar, clk_bar, bank_sel) = nor(read, bank_sel_cbar)
        wordline_en: and3((sense_trig_bar + read_bar), bank_sel, clk_bar)
                    = nor(bank_sel_cbar, nor(sense_trig_bar, read_bar))
                    = nor(bank_sel_cbar, and(sense_trig, read)) sense_trig = 0 during writes
                    =       nor(bank_sel_cbar, sense_trig)
        sampleb:    NAND4(bank_sel, sense_trig_bar, clk_bar, read)
                    = NAND2(AND(bank_sel.clk_bar, sense_trig_bar), read)
                    = NAND2(nor(bank_sel_cbar, sense_trig), read)
                    =       nand2( nor(bank_sel_cbar, sense_trig), read)
        sense_en:           and3(bank_sel, sense_trig, sampleb) (same as tri_en) # ensures sense_en is after sampleb
        tri_en_bar: sense_en_bar
    """

    def create_modules(self):
        self.create_common_modules()
        self.create_2x_nand()
        self.create_decoder_clk()
        self.create_bank_sel()
        self.create_clk_buf()
        self.create_wordline_en()
        self.create_write_buf()
        self.create_precharge_buffers()
        self.create_sense_amp_buf()
        self.create_sample_bar()
        self.create_tri_en_buf()

    def create_2x_nand(self):
        self.nand_x2 = self.create_mod(pnand2, size=2)

    def create_schematic_connections(self):
        connections = [
            ("clk_buf", self.clk_buf,
             ["bank_sel", "clk", "clk_bar", "clk_buf"]),
            ("clk_bar", self.inv, ["clk", "clk_bar_int"]),
            ("bank_sel_cbar", self.nand_x2,
             ["bank_sel", "clk_bar_int", "bank_sel_cbar"]),
            ("wordline_buf", self.wordline_buf,
             ["sense_trig", "bank_sel_cbar", "wordline_en", "wordline_en_bar"]),
            ("write_buf", self.write_buf,
             ["read", "bank_sel_cbar", "write_en", "write_en_bar"])
        ]
        self.add_sample_b_connections(connections)
        connections += [
            ("sample_bar", self.sample_bar,
             ["sample_bar_int", "sample_en_buf", "sample_en_bar"]),
            ("sense_amp_buf", self.sense_amp_buf,
             ["sample_bar_int", "sense_trig", "bank_sel", "sense_en_bar", "sense_en"]),
            ("tri_en_buf", self.tri_en_buf,
             ["sample_bar_int", "sense_trig", "bank_sel", "tri_en_bar", "tri_en"])
        ]
        self.add_precharge_buf_connections(connections)
        self.add_decoder_clk_connections(connections)
        self.add_chip_sel_connections(connections)
        return connections

    def create_precharge_buffers(self):
        assert len(OPTS.precharge_buffers) % 2 == 0, "Number of precharge buffers should be even"
        logic = "pnand3" if self.bank.words_per_row == 1 else "pnand2"
        self.precharge_buf = self.create_mod(LogicBuffer, buffer_stages="precharge_buffers",
                                             logic=logic)

    def add_sample_b_connections(self, connections):
        if self.bank.words_per_row == 1:
            connections.append(("sense_trig_bar", self.inv, ["sense_trig", "sense_trig_bar"]))
            connections.append(("sample_bar_int", self.nand3,
                                ["bank_sel", "read", "sense_trig_bar", "sample_bar_int"]))
        else:
            connections.append(("sense_trig_bar", self.inv, ["sense_trig", "sense_trig_bar"]))
            connections.append(("sample_bar_int", self.nand3,
                                ["bank_sel", "read", "sense_trig_bar", "sample_bar_int"]))

    def add_precharge_buf_connections(self, connections):
        precharge_in = "precharge_trig" if self.use_precharge_trigger else "clk"
        read_conn = ["read"] * (self.bank.words_per_row == 1)
        nets = read_conn + [precharge_in, "bank_sel", "precharge_en_bar", "precharge_en"]
        connections.insert(0, ("precharge_buf", self.precharge_buf, nets))

    def remove_floating_pins(self, candidate_pins, output_pins, mod):
        if isinstance(mod, str):
            mod = getattr(self.bank, mod, None)
        if not mod:
            return
        for pin_name in candidate_pins:
            if isinstance(pin_name, tuple):
                pin_name, dest_pin = pin_name
            else:
                dest_pin = pin_name
            if pin_name not in mod.pins and dest_pin in output_pins:
                output_pins.remove(dest_pin)

    def trim_schematic_pins(self, out_pins):
        self.remove_floating_pins([("en", "write_en"), ("en_bar", "write_en_bar")],
                                  out_pins, "write_driver_array")
        self.remove_floating_pins([("en", "sense_en"), ("en_bar", "sense_en_bar")],
                                  out_pins, "sense_amp_array")
        self.remove_floating_pins([("en", "tri_en"), ("en_bar", "tri_en_bar")],
                                  out_pins, "tri_gate_array")

    def get_schematic_pins(self):
        in_pins = self.get_input_schematic_pins()
        decoder_clk = ["decoder_clk"] * self.use_decoder_clk
        out_pins = decoder_clk + ["clk_buf", "clk_bar", "wordline_en", "precharge_en_bar",
                                  "write_en", "write_en_bar", "sense_en", "sense_en_bar",
                                  "tri_en", "tri_en_bar", "sample_en_bar"]
        self.trim_schematic_pins(out_pins)
        return in_pins, out_pins
