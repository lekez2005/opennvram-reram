import debug
import tech
from base.contact import m1m2, poly as poly_contact, cross_poly, cross_m1m2, \
    cross_m2m3, m2m3, cross_m3m4, m3m4, well as well_contact
from base.design import design, METAL1, POLY, METAL3, METAL2, METAL4, ACTIVE, PWELL
from base.library_import import library_import
from base.unique_meta import Unique
from base.utils import round_to_grid as round_
from base.vector import vector
from base.well_active_contacts import calculate_num_contacts
from globals import OPTS
from pgates.ptx import ptx


@library_import
class reram(design):
    lib_name = "sky130_fd_pr__reram_reram_cell"
    pin_names = ["TE", "BE"]


class body_tap(design, metaclass=Unique):
    @classmethod
    def get_name(cls):
        return f"reram_body_tap"

    def __init__(self):
        design.__init__(self, self.get_name())
        self.width = OPTS.bitcell_width
        self.create_layout()

    def create_layout(self):
        self.height = self.implant_width + self.implant_space
        rail_height = self.height - self.rail_height
        pin_y = 0.5 * self.height - 0.5 * rail_height
        reram_bitcell.add_power_pin(self, pin_y, "gnd", "p", rail_height=rail_height)
        self.add_boundary()


class reram_bitcell(design, metaclass=Unique):
    @classmethod
    def get_name(cls):
        name = f"reram_bitcell_{OPTS.bitcell_tx_size}"
        return name.replace(".", "__")

    def __init__(self):
        design.__init__(self, self.get_name())
        self.width = OPTS.bitcell_width
        self.mid_x = round_(0.5 * self.width)
        self.tx_mults = OPTS.bitcell_tx_mults
        self.tx_size = OPTS.bitcell_tx_size
        self.create_layout()

    def create_layout(self):
        self.add_pin_list(["bl", "br", "wl", "gnd"])
        self.add_access_device()
        self.route_tx_drains()
        self.add_reram()
        self.route_wl()
        self.route_bitlines()
        debug.info(1, f"Bitcell width = {self.width:.5g}")
        debug.info(1, f"Bitcell height = {self.height:.5g}")
        self.add_boundary()
        tech.add_tech_layers(self)

    def get_input_cap(self, pin_name, num_elements: int = 1, wire_length: float = 0.0,
                      interpolate=None, **kwargs):
        if pin_name == "bl":
            pin_name = "br"
        return super().get_input_cap(pin_name, num_elements, wire_length, interpolate,
                                     **kwargs)

    @staticmethod
    def fill_m2_via(obj, offset):
        """Fill m2 in for via with mid offset"""
        fill_height = m1m2.second_layer_height
        _, fill_width = obj.calculate_min_area_fill(fill_height, layer=METAL2)
        obj.add_rect_center(METAL2, offset, width=fill_width,
                            height=fill_height)

    def get_sorted_tx_pins(self, pin_name):
        return list(sorted(self.nmos.get_pins(pin_name), key=lambda x: x.lx()))

    def add_access_device(self):
        finger_width = round_(self.tx_size / self.tx_mults)
        min_width = tech.parameter["min_tx_size"]
        if finger_width < min_width:
            debug.warning(f"finger width {finger_width:.5g} less than "
                          f"{min_width:.5g} so using the min_width")
            finger_width = tech.parameter["min_tx_size"]
        nmos = ptx(width=finger_width, mults=self.tx_mults, tx_type="nmos")

        nmos_poly = nmos.get_pins("G")[0]

        y_offset = round_(0.5 * self.poly_vert_space) - nmos_poly.by()
        x_offset = self.mid_x - 0.5 * nmos.width
        self.nmos = self.add_inst("access", nmos, vector(x_offset, y_offset))
        self.connect_inst(["be", "wl", "br", "gnd"])

    def route_tx_drains(self):
        self.drain_rail_width = rail_width = m2m3.w_2
        allowance = rail_width + self.m2_space

        source_pins = self.get_sorted_tx_pins("S")
        drain_pins = self.get_sorted_tx_pins("D")

        pin_height = source_pins[0].height()

        sample_contact = calculate_num_contacts(self, pin_height - allowance,
                                                layer_stack=m1m2.layer_stack,
                                                return_sample=True)

        bottom_y = source_pins[0].by()
        top_y = max(bottom_y + sample_contact.h_2 + self.m2_space + rail_width,
                    source_pins[0].uy())
        self.top_via_y = top_y - rail_width

        mid_via_y_offsets = [bottom_y + 0.5 * sample_contact.h_2,
                             top_y - 0.5 * sample_contact.h_2]
        rail_ys = [bottom_y, self.top_via_y]
        for pins, via_y, rail_y in zip([source_pins, drain_pins], mid_via_y_offsets,
                                       rail_ys):
            for pin in pins:
                self.add_contact_center(m1m2.layer_stack, vector(pin.cx(), via_y),
                                        size=sample_contact.dimensions)
                self.add_rect(METAL1, vector(pin.lx(), pin.cy()), width=pin.width(),
                              height=via_y - pin.cy())
            self.add_rect(METAL2, vector(pins[0].cx(), rail_y), height=rail_width,
                          width=pins[-1].cx() - pins[0].cx())

        self.source_via_top = mid_via_y_offsets[0] + 0.5 * sample_contact.h_2

    def add_reram(self):
        reram_device = reram()
        x_offset = self.nmos.cx() - 0.5 * reram_device.width + reram_device.width
        nmos_pin = self.nmos.get_pins("S")[0]
        y_offset = nmos_pin.cy() - 0.5 * reram_device.height

        be_pin = reram_device.get_pin("BE")
        y_offset = min(y_offset, self.top_via_y - self.m2_space - be_pin.width())

        self.reram = self.add_inst("mem", reram_device,
                                   vector(x_offset, y_offset), rotate=90)
        self.connect_inst(["bl", "be"])

    def route_wl(self):
        active_to_poly_contact = tech.drc.get("poly_contact_to_active")
        active_to_mid_contact = active_to_poly_contact + 0.5 * poly_contact.contact_width
        contact_mid_y = self.nmos.by() + self.nmos.mod.active_rect.uy() + active_to_mid_contact

        contact_mid_y = max(contact_mid_y,
                            self.top_via_y + self.drain_rail_width + self.m2_space +
                            0.5 * m2m3.h_1)

        self.height = contact_mid_y + 0.5 * poly_contact.h_1 + 0.5 * self.poly_vert_space

        poly_rects = self.get_sorted_tx_pins("G")
        for rect in poly_rects:
            self.add_rect(POLY, rect.ul(), width=rect.width(),
                          height=contact_mid_y + 0.5 * poly_contact.h_1 - rect.uy())
        ext = 0.5 * poly_contact.w_1
        via_offsets = [poly_rects[0].rx() - ext,
                       0.5 * (poly_rects[1].cx() + poly_rects[2].cx()),
                       poly_rects[-1].lx() + ext]
        self.add_rect(METAL1, vector(poly_rects[0].cx(),
                                     contact_mid_y - 0.5 * poly_contact.w_2),
                      width=poly_rects[-1].cx() - poly_rects[0].cx())
        for x_offset in via_offsets:
            self.add_cross_contact_center(cross_poly, vector(x_offset, contact_mid_y))

        offset = vector(via_offsets[1], contact_mid_y)
        self.add_cross_contact_center(cross_m1m2, offset, rotate=True)
        self.add_cross_contact_center(cross_m2m3, offset, rotate=False)
        self.fill_m2_via(self, offset)

        self.add_layout_pin("wl", METAL3, vector(0, contact_mid_y - 0.5 * self.bus_width),
                            width=self.width, height=self.bus_width)

    def route_bitlines(self):
        # add pins
        allowance = self.m4_space
        pin_width = max(self.bus_width, self.m4_width)
        x_offsets = [allowance, self.width - allowance - pin_width]
        pin_names = ["bl", "br"]
        pins = []
        for x_offset, pin_name in zip(x_offsets, pin_names):
            pin = self.add_layout_pin(pin_name, METAL4, vector(x_offset, 0),
                                      width=pin_width, height=self.height)
            pins.append(pin)

        bl_pin, br_pin = pins
        # bl
        te_pin = self.reram.get_pin("TE")
        self.add_rect(METAL3, te_pin.lr(), width=bl_pin.cx() - te_pin.rx(),
                      height=te_pin.height())
        self.add_cross_contact_center(cross_m3m4, vector(bl_pin.cx(), te_pin.cy()),
                                      rotate=True)
        # br
        m3_height = m3m4.w_1
        y_offset = max(te_pin.uy() + self.m3_space,
                       self.source_via_top + self.m2_space,
                       self.get_pin("wl").by() - 1.5 * self.m3_space - m3_height)
        drain_pin = self.get_sorted_tx_pins("D")[1]
        self.add_rect(METAL3, vector(br_pin.cx(), y_offset),
                      width=drain_pin.cx() - br_pin.cx(), height=m3_height)
        via_y = y_offset + 0.5 * m3_height
        self.add_cross_contact_center(cross_m2m3, vector(drain_pin.cx(), via_y))
        self.add_cross_contact_center(cross_m3m4, vector(br_pin.cx(), via_y),
                                      rotate=True)

    @staticmethod
    def add_power_pin(self, y_offset, pin_name, implant_type, rail_height=None):
        rail_height = rail_height or self.rail_height
        max_width = self.width - self.get_space(ACTIVE)
        num_contacts = calculate_num_contacts(self, max_width,
                                              layer_stack=well_contact.layer_stack,
                                              return_sample=False)
        pin_width = self.width + max(m1m2.first_layer_height, m2m3.second_layer_height)
        for layer in [METAL1, METAL3]:
            self.add_layout_pin(pin_name, layer, vector(0, y_offset),
                                width=pin_width, height=rail_height)

        mid_offset = (0.5 * self.width, 0.5 * rail_height + y_offset)
        self.add_contact_center(well_contact.layer_stack, mid_offset, rotate=90,
                                size=[1, num_contacts],
                                implant_type=implant_type, well_type=PWELL)

        num_contacts = calculate_num_contacts(self, self.width - self.m2_space,
                                              layer_stack=m1m2.layer_stack,
                                              return_sample=False)
        self.add_contact_center(m1m2.layer_stack, mid_offset, rotate=90,
                                size=[1, num_contacts])
