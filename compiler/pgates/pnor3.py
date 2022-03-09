from .pnand2 import pnand2


class pnor3(pnand2):
    """
    This module generates gds of a parametrically sized 2-input nor.
    This model use ptx to generate a 2-input nor within a cetrain height.
    """
    mod_name = "nor3"

    nmos_scale = 1
    pmos_scale = 3
    num_tracks = 3

    @classmethod
    def get_class_name(cls):
        return "pnor3"

    def connect_to_gnd(self, _):
        super().connect_to_gnd(self.source_positions)

    def connect_to_vdd(self, _):
        super().connect_to_vdd(self.source_positions[0:1])

    def connect_s_or_d(self, _, __):
        super().connect_s_or_d(self.drain_positions[1:], self.drain_positions)

    def connect_inputs(self):
        y_shifts = [-self.gate_rail_pitch, 0, self.gate_rail_pitch]
        pin_names = ["A", "B", "C"]
        self.add_poly_contacts(pin_names, y_shifts)

    def add_pins(self):
        """ Adds pins for spice netlist """
        self.add_pin_list(["A", "B", "C", "Z", "vdd", "gnd"])

    def get_ptx_connections(self):
        return get_ptx_connections(self)


def get_ptx_connections(self):
    return [
        (self.pmos, ["vdd", "A", "net1", "vdd"]),
        (self.pmos, ["net1", "B", "net2", "vdd"]),
        (self.pmos, ["net2", "C", "Z", "vdd"]),
        (self.nmos, ["Z", "A", "gnd", "gnd"]),
        (self.nmos, ["Z", "B", "gnd", "gnd"]),
        (self.nmos, ["Z", "C", "gnd", "gnd"])
    ]
