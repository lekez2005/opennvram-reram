from base.vector import vector
from .pnand2 import pnand2
from .ptx_spice import ptx_spice


class pnand3(pnand2):
    """
    This module generates gds of a parametrically sized 3-input nand.
    This model use ptx to generate a 3-input nand within a certain height.
    """
    nmos_scale = 2.5
    pmos_scale = 1
    num_tracks = 3

    mod_name = "nand3"

    def connect_to_gnd(self, _):
        super().connect_to_gnd(self.source_positions[0:1])

    def connect_s_or_d(self, _, __):
        super().connect_s_or_d(self.drain_positions, self.drain_positions[1:])

    @classmethod
    def get_class_name(cls):
        return "pnand3"

    def add_pins(self):
        """ Adds pins for spice netlist """
        self.add_pin_list(["A", "B", "C", "Z", "vdd", "gnd"])

    def connect_inputs(self):
        y_shifts = [-self.gate_rail_pitch, 0, self.gate_rail_pitch]
        pin_names = ["A", "B", "C"]
        self.add_poly_contacts(pin_names, y_shifts)

    def get_ptx_connections(self):
        return get_ptx_connections(self)


def get_ptx_connections(self):
    return [
        (self.pmos, ["vdd", "A", "Z", "vdd"]),
        (self.pmos, ["Z", "B", "vdd", "vdd"]),
        (self.pmos, ["Z", "C", "vdd", "vdd"]),
        (self.nmos, ["Z", "C", "net1", "gnd"]),
        (self.nmos, ["net1", "B", "net2", "gnd"]),
        (self.nmos, ["net2", "A", "gnd", "gnd"])
    ]
