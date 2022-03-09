import debug
import tech
from base import utils
from base.analog_cell_mixin import AnalogMixin
from base.contact import m1m2, well as well_contact, poly as poly_contact, \
    cross_m2m3, cross_m3m4, cross_poly, cross_m1m2, m2m3, m3m4
from base.design import design, ACTIVE, METAL1, METAL2, POLY, METAL3
from base.unique_meta import Unique
from base.vector import vector
from base.well_active_contacts import add_power_tap
from globals import OPTS
from modules.precharge import precharge_characterization
from base.utils import round_to_grid as round_
from pgates.ptx import ptx
from pgates.ptx_spice import ptx_spice


class BitlineDischarge(design, precharge_characterization, metaclass=Unique):

    @classmethod
    def get_name(cls, name=None, size=1):
        name = name or f"discharge_{size:.5g}"
        return name.replace(".", "__")

    def __init__(self, name=None, size=1):
        design.__init__(self, self.get_name(name, size))
        debug.info(2, "create single precharge cell: {0}".format(name))
        self.size = size

        self.create_layout()
        self.DRC_LVS()

    def create_layout(self):
        self.add_pins()
        self.add_tx()
        self.add_enable_pins()
        self.add_bitlines()
        self.add_tx_connections()
        self.add_power()
        self.flatten_tx()
        tech.add_tech_layers(self)
        self.add_boundary()

    def add_pins(self):
        self.add_pin_list(["bl", "br", "bl_reset", "br_reset", "gnd"])

    def add_tx(self):
        self.bitcell = self.create_mod_from_str(OPTS.bitcell)
        self.width = self.bitcell.width
        self.mid_x = round_(0.5 * self.width)

        min_width = tech.parameter["min_tx_size"]
        ptx_width = round_(self.size * min_width)

        finger_width = max(min_width, round_(ptx_width / 2))
        nmos = ptx(width=finger_width, mults=4, tx_type="nmos")

        well_contact_mid_y = 0.5 * self.rail_height
        well_contact_active_top = well_contact_mid_y + 0.5 * well_contact.first_layer_width
        self.bottom_space = well_contact_active_top + self.get_space(ACTIVE)

        y_offset = self.bottom_space - nmos.active_rect.by()
        x_offset = self.mid_x - 0.5 * nmos.width

        self.nmos = self.add_inst("nmos", nmos, vector(x_offset, y_offset))
        self.connect_inst([], check=False)

    def add_tx_connections(self):
        tx = self.nmos.mod
        tx_spice = ptx_spice(width=tx.tx_width, mults=2,
                             tx_type=tx.tx_type, tx_length=tx.tx_length)
        self.add_mod(tx_spice)

        offset = vector(0, 0)
        self.add_inst("bl_inst", tx_spice, offset)
        self.connect_inst(["bl", "bl_reset", "gnd", "gnd"])
        self.add_inst("br_inst", tx_spice, offset)
        self.connect_inst(["br", "br_reset", "gnd", "gnd"])

    def add_enable_pins(self):
        # first assume bl_reset will be centered at middle poly contact\
        enable_pin_space = 1.4 * self.bus_space

        active_rect = max(self.nmos.get_layer_shapes(ACTIVE),
                          key=lambda x: x.width * x.height)
        active_to_poly_contact = tech.drc.get("poly_contact_to_active")
        active_to_mid_contact = active_to_poly_contact + 0.5 * poly_contact.contact_width
        contact_mid_y = active_rect.uy() + active_to_mid_contact

        bl_reset_y = contact_mid_y - 0.5 * self.bus_width
        br_reset_y = bl_reset_y - enable_pin_space - self.bus_width
        self.bitline_via_height = max(m1m2.h_2, m2m3.h_1, m2m3.w_2, m3m4.w_1)
        enable_to_via_space = (max(self.get_line_end_space(METAL2),
                                   self.get_line_end_space(METAL3)) + 0.5 * m1m2.h_2 -
                               0.5 * self.bus_width)
        bitline_via_y = br_reset_y - enable_to_via_space - self.bitline_via_height

        # check if it's far enough from power rail and shift enable pins up if appropriate
        min_bitline_via_y = max(self.rail_height + enable_pin_space,
                                active_rect.by())
        if bitline_via_y < min_bitline_via_y:
            y_shift = utils.ceil(min_bitline_via_y - bitline_via_y)
            bitline_via_y += y_shift
            bl_reset_y += y_shift
            br_reset_y += y_shift
        # check contact mid_y to avoid bitline via
        contact_mid_y = max(contact_mid_y, bitline_via_y + self.bitline_via_height +
                            self.get_line_end_space(METAL2) + 0.5 * m1m2.h_2)

        self.bitline_via_y = bitline_via_y
        self.height = max(contact_mid_y + 0.5 * poly_contact.h_1,
                          bl_reset_y + 0.5 * self.bus_width + 0.5 * m2m3.h_1)

        # add poly contacts
        poly_rects = list(sorted(self.nmos.get_pins("G"), key=lambda x: x.lx()))
        poly_top = contact_mid_y + 0.5 * poly_contact.h_1
        x_offsets = []
        for left_rect, right_rect in [poly_rects[:2], poly_rects[2:]]:
            x_offset = 0.5 * (left_rect.cx() + right_rect.cx())
            x_offsets.append(x_offset)
            for rect in [left_rect, right_rect]:
                self.add_rect(POLY, rect.ul(), width=rect.width(),
                              height=poly_top - rect.uy())
            self.add_cross_contact_center(cross_poly, vector(x_offset, contact_mid_y))

        y_offsets = [bl_reset_y, br_reset_y]
        pin_names = ["bl_reset", "br_reset"]

        for i in range(2):
            y_offset = y_offsets[i]
            self.add_layout_pin(pin_names[i], METAL3, vector(0, y_offset),
                                width=self.width, height=self.bus_width)

            offset = vector(x_offsets[i], contact_mid_y)
            self.add_cross_contact_center(cross_m1m2, offset, rotate=True)
            via_offset = vector(offset.x, y_offset + 0.5 * self.bus_width)
            self.add_cross_contact_center(cross_m2m3, via_offset)
            self.add_rect(METAL2, via_offset - vector(0.5 * m2m3.w_1, 0),
                          width=m2m3.w_1, height=offset.y - via_offset.y)

    def add_bitlines(self):
        pin_names = ["bl", "br"]
        drain_pins = list(sorted(self.nmos.get_pins("D"), key=lambda x: x.lx()))
        for i, pin_name in enumerate(pin_names):
            drain_pin = drain_pins[i]
            bitcell_pin = self.bitcell.get_pin(pin_name)
            layout_pin = self.add_layout_pin(pin_name, bitcell_pin.layer,
                                             vector(bitcell_pin.lx(), 0),
                                             width=bitcell_pin.width(),
                                             height=self.height)
            y_offset = self.bitline_via_y + 0.5 * self.bitline_via_height

            self.add_cross_contact_center(cross_m2m3, vector(layout_pin.cx(), y_offset))
            self.add_cross_contact_center(cross_m3m4, vector(layout_pin.cx(), y_offset),
                                          rotate=True)
            self.add_contact_center(m1m2.layer_stack, vector(drain_pin.cx(), y_offset))

            self.add_rect(METAL2, vector(drain_pin.cx(), y_offset - 0.5 * m1m2.h_2),
                          height=m1m2.h_2, width=layout_pin.cx() - drain_pin.cx())

    def add_power(self):
        pin, cont, well_type = add_power_tap(self, 0, "gnd", self.width)
        AnalogMixin.add_m1_m3_power_via(self, pin, add_m3_pin=True)
        width = round_(self.poly_pitch - self.get_parallel_space(METAL1))
        for pin in self.nmos.get_pins("S"):
            self.add_rect(METAL1, vector(pin.cx() - 0.5 * width, 0),
                          width=width, height=pin.uy())

    def flatten_tx(self):
        ptx.flatten_tx_inst(self, self.nmos)
