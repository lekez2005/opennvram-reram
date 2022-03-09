import debug
from base import contact, utils
from base import design
from base.analog_cell_mixin import AnalogMixin
from base.contact import m1m2, poly as poly_contact
from base.design import METAL2, ACTIVE, METAL1, POLY, NIMP, PWELL, PIMP, TAP_ACTIVE
from base.geometry import MIRROR_X_AXIS
from base.vector import vector
from base.well_active_contacts import calculate_contact_width
from base.well_implant_fills import calculate_tx_metal_fill
from globals import OPTS
from pgates.ptx import ptx
from tech import drc, info
import tech


def get_inputs_for_pin(self, name):
    if name in ["bl", "br"]:
        return ["sel", name + "_out"]
    elif name in ["bl_out", "br_out"]:
        return ["sel", name.replace("_out", "")]
    return super(design.design, self).get_inputs_for_pin(name)


class single_level_column_mux(AnalogMixin, design.design):
    """
    This module implements the columnmux bitline cell used in the design.
    Creates a single columnmux cell.
    """

    def __init__(self):
        tx_size = OPTS.column_mux_size
        name = "single_level_column_mux_{}".format(tx_size).replace(".", "__")
        design.design.__init__(self, name)
        debug.info(2, "create single column mux cell: {0}".format(name))

        self.bitcell = self.create_mod_from_str(OPTS.bitcell)

        self.ptx_width = tx_size * drc["minwidth_tx"]
        self.tx_mults = 2
        self.add_pin_list(["bl", "br", "bl_out", "br_out", "sel", "gnd"])
        self.create_layout()

    def get_inputs_for_pin(self, name):
        return get_inputs_for_pin(self, name)

    def create_layout(self):

        self.width = self.bitcell.width
        self.determine_tx_mults()
        self.create_ptx()
        self.add_ptx()
        self.connect_gates()
        self.add_bitline_fills()
        self.add_bitline_pins()
        self.add_body_contacts()
        self.add_well_implants()
        self.add_boundary()
        tech.add_tech_layers(self)
        self.augment_power_pins()

    def determine_tx_mults(self):
        # Need M2 bitlines on both sides of transistors
        m2_space = self.get_parallel_space(METAL2)
        m1_m2_extension = 0.5 * (contact.m1m2.second_layer_width - contact.active.second_layer_width)
        total_side_space = 2 * (0.5 * m2_space + self.m2_width + m2_space + m1_m2_extension)
        available_active_width = self.bitcell.width - total_side_space
        tx_mults = 1
        while True:
            sample_ptx = ptx(mults=tx_mults, tx_type="nmos")
            active_rect = max(sample_ptx.get_layer_shapes(ACTIVE), key=lambda x: x.width)
            if active_rect.width > available_active_width:
                tx_mults -= 1
                break
            tx_mults += 1
        self.tx_mults = tx_mults

    def create_ptx(self):
        self.tx = ptx(width=self.ptx_width / self.tx_mults, mults=self.tx_mults,
                      tx_type="nmos")
        self.add_mod(self.tx)

    def add_ptx(self):
        """ Create the two pass gate NMOS transistors to switch the bitlines"""

        poly_rect = max(self.tx.get_layer_shapes(POLY), key=lambda x: x.height)
        poly_to_cont_mid = poly_rect.height - 0.5 * contact.poly.first_layer_height

        source_pin = self.tx.get_pins("S")[0]

        # position of bottom via
        drain_via_y = source_pin.uy() - m1m2.height
        source_via_y = min(source_pin.by(), drain_via_y + 0.5 * m1m2.height +
                           0.5 * m1m2.h_2 - self.m2_width -
                           self.get_line_end_space(METAL2) - m1m2.h_2)
        self.source_via_y = source_via_y - source_pin.by()
        self.drain_via_y = drain_via_y - source_pin.by()

        # bottom fill
        res = calculate_tx_metal_fill(self.tx.tx_width, self.tx, contact_if_none=True)
        _, _, self.fill_width, self.fill_height = res

        line_end_space = max(self.get_line_end_space(METAL1),
                             self.get_line_end_space(METAL2))

        self.sel_via_y = 0.5 * m1m2.height

        required_space = self.sel_via_y + 0.5 * max(m1m2.h_1, m1m2.h_2) + line_end_space

        min_m1_y = min(source_via_y + 0.5 * m1m2.height - 0.5 * m1m2.h_1,
                       source_pin.uy() - self.fill_height)
        bottom_space = required_space - min_m1_y

        # add transistors
        x_offset = 0.5 * self.width - 0.5 * self.tx.width
        self.br_inst = self.add_inst("br_mux", mod=self.tx, offset=vector(x_offset, bottom_space))
        self.connect_inst(["br", "sel", "br_out", "gnd"])

        # align mid contacts of bl and br muxes
        contact_mid_y = poly_rect.by() + poly_to_cont_mid
        bl_y_offset = bottom_space + 2 * contact_mid_y
        self.bl_inst = self.add_inst("bl_mux", mod=self.tx, offset=vector(x_offset, bl_y_offset),
                                     mirror=MIRROR_X_AXIS)
        self.connect_inst(["bl", "sel", "bl_out", "gnd"])

        self.contact_mid_y = contact_mid_y + bottom_space
        self.mid_x = 0.5 * self.width

    def connect_gates(self):
        """ Connect the poly gate of the two pass transistors """

        rail_x = -0.5 * self.m1_width
        gate_pins = list(sorted(self.bl_inst.get_pins("G"), key=lambda x: x.lx()))

        # join poly if horz poly
        horz_poly = poly_contact.first_layer_width > gate_pins[0].width()
        if horz_poly:
            mid_x = 0.5 * (gate_pins[0].cx() + gate_pins[-1].cx())
            self.add_rect_center(POLY, vector(mid_x, gate_pins[0].cy()),
                                 width=gate_pins[-1].cx() - gate_pins[0].cx(),
                                 height=poly_contact.h_1)

        gate_right = max(gate_pins, key=lambda x: x.rx()).rx()

        self.add_rect("metal1", offset=vector(rail_x, gate_pins[0].cy() - 0.5 * self.m1_width),
                      width=gate_right - rail_x)

        bend_y = self.sel_via_y + 0.5 * m1m2.h_1 - self.m1_width
        self.add_rect("metal1", offset=vector(rail_x, bend_y),
                      height=gate_pins[0].cy() - bend_y)
        self.add_rect("metal1", offset=vector(rail_x, bend_y), width=self.mid_x - rail_x)
        self.add_via(layers=contact.contact.m1m2_layers, offset=vector(self.mid_x - 0.5 * m1m2.width, 0))

        _, pin_height = self.calculate_min_area_fill(self.m2_width, layer=METAL2)
        pin_height = max(pin_height, m1m2.second_layer_height)

        pin_top = m1m2.height - 0.5 * m1m2.height + 0.5 * m1m2.h_2
        self.add_layout_pin(text="sel", layer="metal2",
                            offset=vector(self.mid_x - 0.5 * self.m1_width,
                                          pin_top - pin_height), height=pin_height)

    def add_bitline_fills(self):
        """Add fills to sources and drains to prevent min area issues or m1m2 space issue"""
        gate_pin = self.bl_inst.get_pins("G")[0]
        # Add fills
        for inst in [self.bl_inst, self.br_inst]:
            pins = list(sorted(inst.get_pins("D") + inst.get_pins("S"), key=lambda x: x.lx()))
            for i in range(self.tx_mults + 1):
                pin = pins[i]
                if i == 0:
                    x_offset = pin.lx()
                elif i == self.tx_mults:
                    x_offset = pin.rx() - self.fill_width
                else:
                    x_offset = pin.cx() - 0.5 * self.fill_width

                if pin.cy() > gate_pin.cy():
                    y_offset = pin.by()
                else:
                    y_offset = pin.uy() - self.fill_height

                self.add_rect(METAL1, offset=vector(x_offset, y_offset),
                              width=self.fill_width, height=self.fill_height)

    def add_bitline_pins(self):
        """ Add the top and bottom pins to this cell """

        active_rect = max(self.tx.get_layer_shapes(ACTIVE), key=lambda x: x.width)

        x_offsets = [active_rect.lx() - self.get_parallel_space(METAL2) - self.m2_width,
                     active_rect.rx() + self.get_parallel_space(METAL2)]
        x_offsets = [x + self.bl_inst.lx() for x in x_offsets]

        insts = [self.bl_inst, self.br_inst]
        pin_names = ["bl", "br"]

        self.top_m1_rail_y = (self.bl_inst.get_pins("S")[0].uy() - self.source_via_y -
                              0.5 * m1m2.height + 0.5 * m1m2.h_2 - self.m2_width)

        self.calculate_body_contacts()

        for i in range(2):
            x_offset = x_offsets[i]
            source_pins = insts[i].get_pins("S")
            drain_pins = insts[i].get_pins("D")
            reference_pin = source_pins[0]
            bitcell_pin = self.bitcell.get_pin(pin_names[i])

            if i == 0:
                top_via_y = reference_pin.uy() - self.source_via_y - 0.5 * m1m2.height
                bot_via_y = reference_pin.uy() - self.drain_via_y - 0.5 * m1m2.height
            else:
                bot_via_y = reference_pin.by() + self.source_via_y + 0.5 * m1m2.height
                top_via_y = reference_pin.by() + self.drain_via_y + 0.5 * m1m2.height

            bot_rail_y = bot_via_y - 0.5 * m1m2.h_2
            top_rail_y = top_via_y + 0.5 * m1m2.h_2 - self.m2_width

            via_y_offsets = [top_via_y, bot_via_y]
            rail_y_offsets = [top_rail_y, bot_rail_y]

            for j in range(2):
                pins = source_pins if j == 0 else drain_pins
                for pin in pins:
                    self.add_contact_center(m1m2.layer_stack,
                                            vector(pin.cx(), via_y_offsets[j]))

                if i == 0:
                    x_end, x_start = pins[-1].cx(), x_offset
                else:
                    x_end, x_start = pins[-0].cx(), x_offset + self.m2_width

                if j == 0:
                    y_bend = (self.top_m1_rail_y + self.m2_width +
                              self.get_line_end_space(METAL2))
                    pin_name = pin_names[i]
                    pin_height = max(self.height - y_bend, 2 * self.m2_width)
                    pin_y = y_bend
                    self.add_rect(METAL2, vector(x_offset, rail_y_offsets[j]),
                                  height=y_bend + self.m2_width - rail_y_offsets[j])
                else:
                    y_bend = self.sel_via_y - 0.5 * self.m2_width
                    pin_name = f"{pin_names[i]}_out"
                    pin_y = y_bend - self.m2_width
                    pin_height = 2 * self.m2_width
                    self.add_rect(METAL2, vector(x_offset, y_bend),
                                  height=rail_y_offsets[j] - y_bend)

                self.add_rect(METAL2, vector(x_start, rail_y_offsets[j]),
                              width=x_end - x_start)

                self.add_rect(METAL2, offset=vector(x_start, y_bend),
                              width=bitcell_pin.cx() - x_start)

                self.add_layout_pin(pin_name, METAL2, offset=vector(bitcell_pin.lx(), pin_y),
                                    width=bitcell_pin.width(),
                                    height=pin_height)

        self.height = max(self.height, self.get_pin("bl").uy())

    def add_well_implants(self):
        layers = [NIMP]
        if info["has_pwell"]:
            layers.append(PWELL)
        for layer in layers:
            tx_rect = max(self.tx.get_layer_shapes(layer), key=lambda x: x.width * x.height)
            x_offset = min(0, tx_rect.lx() + self.bl_inst.lx())
            x_right = max(self.width, tx_rect.rx() + self.bl_inst.lx())
            y_offset = self.br_inst.by() + tx_rect.by()
            if layer == PWELL:
                y_top = self.contact_well_top
            else:
                y_top = self.bl_inst.by() + self.tx.height - tx_rect.by()

            self.add_rect(layer, offset=vector(x_offset, y_offset), width=x_right - x_offset,
                          height=y_top - y_offset)

    def calculate_body_contacts(self):
        # calculate number of contacts
        self.contact_pitch = self.contact_width + self.contact_spacing
        active_height = contact.well.first_layer_width

        pimplant_height = max(self.implant_width,
                              active_height + 2 * self.implant_enclose_active)
        self.body_contact_pimplant_height = pimplant_height

        nimplant_rect = max(self.bl_inst.get_layer_shapes(NIMP), key=lambda x: x.uy())
        self.nimplant_top = nimplant_top = nimplant_rect.uy()

        # based on M1's
        top_m1_rail_y = self.top_m1_rail_y
        min_gnd_pin_y = top_m1_rail_y + self.m2_width + self.get_line_end_space(METAL1)
        # based on actives space
        active_top = max(self.bl_inst.get_layer_shapes(ACTIVE), key=lambda x: x.uy()).uy()
        active_space = drc.get("active_to_body_active", self.get_space(ACTIVE))
        contact_mid_y = active_top + active_space + 0.5 * active_height

        # based on poly to active
        contact_mid_y = max(contact_mid_y, active_top + self.poly_extend_active +
                            self.poly_to_active + 0.5 * active_height)

        contact_mid_y = max(contact_mid_y,
                            min_gnd_pin_y + 0.5 * self.rail_height,
                            nimplant_top + 0.5 * pimplant_height)
        self.contact_mid_y = contact_mid_y
        self.height = self.contact_mid_y + 0.5 * self.rail_height

    def add_body_contacts(self):
        active_height = contact.well.first_layer_width
        active_width, body_contact = calculate_contact_width(self, self.width, active_height)
        contact_mid_y = self.contact_mid_y
        pimplant_height = self.body_contact_pimplant_height

        # pimplant
        pimplant_y = self.nimplant_top
        pimplant_height = max(pimplant_height,
                              contact_mid_y + 0.5 * active_height +
                              self.implant_enclose_active - pimplant_y)
        pimplant_width = active_width + 2 * self.implant_enclose_active

        self.add_rect_center(PIMP, offset=vector(self.mid_x, pimplant_y + 0.5 * pimplant_height),
                             height=pimplant_height, width=pimplant_width)
        # contact
        self.add_contact_center(body_contact.layer_stack, rotate=90,
                                offset=vector(self.mid_x, contact_mid_y), size=body_contact.dimensions)
        # active
        self.add_rect_center(TAP_ACTIVE, vector(self.mid_x, contact_mid_y),
                             width=active_width, height=active_height)

        # gnd pin
        pin_y_offset = contact_mid_y - 0.5 * self.rail_height
        pin_width = max(self.width, body_contact.second_layer_height)
        self.add_layout_pin("gnd", "metal1", offset=vector(0, pin_y_offset), width=pin_width, height=self.rail_height)

        self.contact_well_top = contact_mid_y + 0.5 * active_height + self.well_enclose_active
