from base.vector import vector
from .pnand2 import pnand2
from .ptx_spice import ptx_spice


class pnor2(pnand2):
    """
    This module generates gds of a parametrically sized 2-input nor.
    This model use ptx to generate a 2-input nor within a cetrain height.
    """
    mod_name = "nor2"

    nmos_scale = 1
    pmos_scale = 2
    num_tracks = 2

    @classmethod
    def get_class_name(cls):
        return "pnor2"

    def connect_to_gnd(self, _):
        super().connect_to_gnd(self.source_positions)

    def connect_to_vdd(self, _):
        super().connect_to_vdd(self.source_positions[0:1])

    def connect_s_or_d(self, _, __):
        super().connect_s_or_d(self.source_positions[1:], self.drain_positions)

    def get_ptx_connections(self):
        return get_ptx_connections(self)


def get_ptx_connections(self):
    return [
        (self.pmos, ["vdd", "A", "net1", "vdd"]),
        (self.pmos, ["net1", "B", "Z", "vdd"]),
        (self.nmos, ["Z", "A", "gnd", "gnd"]),
        (self.nmos, ["Z", "B", "gnd", "gnd"]),
    ]
