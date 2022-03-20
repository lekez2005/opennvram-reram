import tech
from base import utils, well_active_contacts
from base.analog_cell_mixin import AnalogMixin
from base.contact import well as well_contact, poly as poly_contact, cross_poly, m1m2, m2m3
from base.design import design, ACTIVE, METAL1, POLY
from base.unique_meta import Unique
from base.utils import round_to_grid as round_g
from base.vector import vector
from globals import OPTS
from pgates.ptx import ptx
from pgates.ptx_spice import ptx_spice


class BitcellAlignedPgate(design, metaclass=Unique):
    mod_name = None

    def create_layout(self):
        raise NotImplemented

    @classmethod
    def get_name(cls, size, name=None):
        raise NotImplemented

    def __init__(self, size, name=None):
        name = name or self.get_name(size, name)
        self.size = size
        design.__init__(self, name)
        self.create_layout()

    @staticmethod
    def get_sorted_pins(tx_inst, pin_name):
        return list(sorted(tx_inst.get_pins(pin_name), key=lambda x: x.lx()))

    def create_ptx(self, size, is_pmos=False, **kwargs):
        width = size * tech.spice["minwidth_tx"]
        if is_pmos:
            width *= tech.parameter["beta"]
        return self.create_ptx_by_width(width, is_pmos, **kwargs)

    def create_ptx_by_width(self, width, is_pmos=False, **kwargs):
        if is_pmos:
            tx_type = "pmos"
        else:
            tx_type = "nmos"
        tx = ptx(width=width, tx_type=tx_type, **kwargs)
        self.add_mod(tx)
        return tx

    def create_ptx_spice(self, tx: ptx, mults=1, scale=1):
        tx_spice = ptx_spice(width=tx.tx_width * scale, mults=mults,
                             tx_type=tx.tx_type, tx_length=tx.tx_length)
        self.add_mod(tx_spice)
        return tx_spice

    def flatten_tx(self, *args):
        if not args:
            args = [x for x in self.insts if isinstance(x.mod, ptx) and
                    not isinstance(x.mod, ptx_spice)]
        for tx_inst in args:
            ptx.flatten_tx_inst(self, tx_inst)

    def create_modules(self):
        self.bitcell = self.create_mod_from_str(OPTS.bitcell)
        self.width = self.bitcell.width
        self.mid_x = utils.round_to_grid(0.5 * self.width)

    def calculate_bottom_space(self):
        well_contact_mid_y = 0.5 * self.rail_height
        well_contact_active_top = well_contact_mid_y + 0.5 * well_contact.first_layer_width
        return well_contact_active_top + self.get_space(ACTIVE)

    def add_mid_poly_via(self, nmos_poly, mid_y, min_via_x=None):
        horz_poly = poly_contact.first_layer_width > nmos_poly[0].width()
        x_offsets = []

        for i in [1, 2]:
            # add poly contact
            if horz_poly:
                x_offset = min_via_x or nmos_poly[i].cx()
            else:
                x_offset = nmos_poly[i].cx()
            x_offsets.append(x_offset)

            if horz_poly and i == 1:
                self.add_cross_contact_center(cross_poly, vector(x_offset, mid_y))
            elif not horz_poly:
                self.add_contact_center(poly_contact.layer_stack, vector(x_offset, mid_y))

        # horizontal join poly contact
        layer = POLY if horz_poly else METAL1
        height = (poly_contact.first_layer_height
                  if horz_poly else poly_contact.second_layer_height)
        self.add_rect(layer, vector(nmos_poly[1].cx(), mid_y - 0.5 * height),
                      height=height, width=nmos_poly[2].cx() - nmos_poly[1].cx())

        return x_offsets[0]

    def calculate_poly_via_offsets(self, tx_inst):
        poly_rects = self.get_sorted_pins(tx_inst, "G")
        left_via_x = poly_rects[0].rx() - 0.5 * poly_contact.w_1
        right_via_x = poly_rects[1].lx() + 0.5 * poly_contact.w_1
        return left_via_x, right_via_x

    def join_poly(self, nmos_inst, pmos_inst, indices=None, mid_y=None):
        all_nmos_poly = self.get_sorted_pins(nmos_inst, "G")
        all_pmos_poly = self.get_sorted_pins(pmos_inst, "G")
        if indices is None:
            num_poly = len(all_nmos_poly)
            indices = [(i, i) for i in range(num_poly)]

        for nmos_index, pmos_index in indices:
            nmos_poly = all_nmos_poly[nmos_index]
            pmos_poly = all_pmos_poly[pmos_index]
            bottom_poly, top_poly = sorted([nmos_poly, pmos_poly], key=lambda x: x.by())
            width = nmos_poly.width()
            if round_g(bottom_poly.lx()) == round_g(top_poly.lx()):
                self.add_rect(POLY, bottom_poly.ul(), width=width,
                              height=top_poly.by() - bottom_poly.uy())
            else:
                if mid_y is None:
                    mid_y = 0.5 * (bottom_poly.uy() + top_poly.by()) - 0.5 * width
                self.add_rect(POLY, bottom_poly.ul(), width=width,
                              height=mid_y + width - bottom_poly.uy())
                self.add_rect(POLY, vector(bottom_poly.lx(), mid_y), height=width,
                              width=top_poly.cx() - bottom_poly.lx())
                self.add_rect(POLY, vector(top_poly.lx(), mid_y), width=width,
                              height=top_poly.by() - mid_y)

    def extend_tx_well(self, tx_inst, well_type, pin, cont=None):
        well_active_contacts.extend_tx_well(self, tx_inst, pin)

    def add_power_tap(self, y_offset, pin_name, tx_inst, add_m3=True):
        pin_width = self.width
        if add_m3:
            pin_width += max(m1m2.first_layer_height, m2m3.second_layer_height)

        pin, cont, well_type = well_active_contacts.add_power_tap(self, y_offset,
                                                                  pin_name, pin_width)

        # add well
        self.extend_tx_well(tx_inst, well_type, pin, cont)

        if add_m3:
            AnalogMixin.add_m1_m3_power_via(self, pin)
        return pin, cont, well_type

    def route_pin_to_power(self, pin_name, pin):
        power_pins = self.get_pins(pin_name)
        power_pin = min(power_pins, key=lambda x: abs(x.cy() - pin.cy()))
        self.add_rect(METAL1, vector(pin.lx(), pin.cy()), width=pin.width(),
                      height=power_pin.cy() - pin.cy())

    def route_tx_to_power(self, tx_inst, tx_pin_name="D", pin_indices=None):
        pin_name = "vdd" if tx_inst.mod.tx_type.startswith("p") else "gnd"
        power_pins = self.get_pins(pin_name)
        power_pin = min(power_pins, key=lambda x: abs(x.cy() - tx_inst.cy()))

        if pin_indices:
            all_pins = self.get_sorted_pins(tx_inst, tx_pin_name)
            all_pins = [all_pins[i] for i in pin_indices]
        else:
            all_pins = tx_inst.get_pins(tx_pin_name)
        for tx_pin in all_pins:
            # todo make configurable
            width = round_g(1.5 * self.m1_width)
            if tx_pin.cy() >= power_pin.cy():
                y_offset = tx_pin.uy()
            else:
                y_offset = tx_pin.by()
            self.add_rect(METAL1, vector(tx_pin.cx() - 0.5 * width, y_offset),
                          width=width, height=power_pin.cy() - y_offset)

    @staticmethod
    def calculate_active_to_poly_cont_mid(tx_type):
        """Distance from edge of active to middle of poly contact"""
        return ptx.calculate_active_to_poly_cont_mid(tx_type)
