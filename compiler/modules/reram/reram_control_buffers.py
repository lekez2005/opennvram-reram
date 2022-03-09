import tech
from modules.baseline_latched_control_buffers import LatchedControlBuffers
from modules.logic_buffer import LogicBuffer


class ReRamControlBuffers(LatchedControlBuffers):
    def create_layout(self):
        super().create_layout()
        tech.add_tech_layers(self)

    def create_2x_nand(self):
        self.nand_x2 = self.nand

    def create_precharge_buffers(self):
        self.br_reset_buf = self.create_mod(LogicBuffer, buffer_stages="br_reset_buffers",
                                            logic="pnor2")

        self.bl_reset_buf = self.create_mod(LogicBuffer,
                                            buffer_stages="bl_reset_buffers",
                                            logic="pnand3")

    def add_precharge_buf_connections(self, connections):
        precharge_in = "precharge_trig" if self.use_precharge_trigger else "clk"

        if not self.use_chip_sel:
            connections.insert(0, ("bank_sel_bar", self.inv, ["bank_sel", "bank_sel_bar"]))
        connections.insert(1, ("nor_read_clk", self.nor, ["read", "clk", "nor_read_clk"]))
        connections.insert(2, ("br_reset", self.br_reset_buf,
                               ["nor_read_clk", "bank_sel_bar", "br_reset", "br_reset_bar"]))

        connections.insert(3, ("read_bar", self.inv, ["read", "read_bar"]))
        connections.insert(4, ("bl_reset", self.bl_reset_buf,
                               ["bank_sel", precharge_in, "read_bar", "bl_reset_bar",
                                "bl_reset"]))

    def get_schematic_pins(self):
        in_pins, out_pins = super().get_schematic_pins()
        out_pins.remove("precharge_en_bar")
        out_pins.extend(["bl_reset", "br_reset"])

        return in_pins, out_pins
