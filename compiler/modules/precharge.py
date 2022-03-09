import debug
from base import contact
from base import design
from base import utils
from base.contact import m1m2, m2m3, m3m4, well as well_contact
from base.design import METAL2, METAL1, METAL3, NIMP, TAP_ACTIVE, NWELL, PIMP
from base.unique_meta import Unique
from base.vector import vector
from base.well_active_contacts import calculate_contact_width, calculate_num_contacts
from globals import OPTS
from pgates.ptx_spice import ptx_spice
from tech import drc, parameter, layer as tech_layers, add_tech_layers, info


class precharge_characterization:
    def is_delay_primitive(self):
        return True

    def get_char_data_size(self: design):
        return self.size

    def get_driver_resistance(self, pin_name, use_max_res=False,
                              interpolate=None, corner=None):
        resistance = self.lookup_resistance(pin_name, interpolate, corner)
        if resistance:
            return resistance / self.size
        return self.pmos.get_driver_resistance("d", use_max_res,
                                               interpolate=True, corner=corner)

    def get_input_cap(self: design, pin_name, num_elements: int = 1, wire_length: float = 0.0,
                      interpolate=None, **kwargs):
        total_cap, cap_per_unit = super().get_input_cap(pin_name=pin_name,
                                                        num_elements=self.size,
                                                        wire_length=wire_length, **kwargs)
        return total_cap * num_elements, cap_per_unit

    def get_input_cap_from_instances(self: design, pin_name, wire_length: float = 0.0,
                                     **kwargs):
        total_cap, cap_per_unit = super().get_input_cap_from_instances(pin_name, wire_length,
                                                                       **kwargs)
        # super class method doesn't consider size in calculating
        cap_per_unit /= self.size
        return total_cap, cap_per_unit

    def compute_input_cap(self: design, pin_name, wire_length: float = 0.0):
        total_cap = super().compute_input_cap(pin_name, wire_length)
        # super class method doesn't consider size in calculating
        cap_per_unit = total_cap / self.size
        return total_cap, cap_per_unit

    def get_char_data_file_suffixes(self, **kwargs):
        return [("beta", parameter["beta"])]

    def get_char_data_name(self, **kwargs) -> str:
        """
        name by which module was characterized
        :return:
        """
        return "{}_{}".format(self.__class__.__name__, self.bitcell.name)


class precharge(precharge_characterization, design.design):
    """
    Creates a single precharge cell
    This module implements the precharge bitline cell used in the design.
    """

    def __init__(self, name=None, size=1):
        name = name or f"precharge_{size:5.5g}"
        design.design.__init__(self, name)
        debug.info(2, "create single precharge cell: {0}".format(name))

        self.bitcell = self.create_mod_from_str(OPTS.bitcell)

        self.beta = parameter["beta"]
        self.ptx_width = utils.round_to_grid(size * self.beta * parameter["min_tx_size"])
        self.size = self.ptx_width / (self.beta * parameter["min_tx_size"])
        self.width = self.bitcell.width

        self.add_pins()
        self.create_layout()
        self.DRC_LVS()

    def add_pins(self):
        self.add_pin_list(["bl", "br", "en", "vdd"])

    def create_layout(self):
        self.set_layout_constants()
        self.create_ptx()
        self.connect_input_gates()
        self.add_nwell_contacts()
        self.add_active_contacts()
        self.connect_bitlines()
        self.drc_fill()
        add_tech_layers(self)
        self.add_ptx_inst()
        self.add_boundary()

    def set_layout_constants(self):

        self.mid_x = 0.5 * self.width

        # TODO should depend on bitcell width
        self.mults = 3

        self.well_contact_active_height = contact.well.first_layer_width
        self.well_contact_implant_height = max(self.implant_width,
                                               self.well_contact_active_height +
                                               2 * self.implant_enclose_active)

        # nwell contact top space requirement
        poly_to_well_cont_top = (self.poly_to_active + 0.5 * self.well_contact_active_height +
                                 0.5 * self.well_contact_implant_height)

        # space to add poly contacts
        active_to_poly_top = max(self.get_line_end_space(METAL1),
                                 self.get_line_end_space(METAL2))  # space to the en metal1
        active_to_poly_top += 0.5 * max(contact.poly.second_layer_width,
                                        m1m2.second_layer_width)  # space to middle of poly contact
        self.active_to_poly_cont_mid = active_to_poly_top
        self.poly_top_space = active_to_poly_top = self.active_to_poly_cont_mid + 0.5 * contact.poly.first_layer_height

        # en pin top space requirement
        self.en_rail_height = self.bus_width
        # space based on M2 enable pin
        self.active_to_enable_top = self.get_line_end_space(METAL2) + self.en_rail_height
        en_rail_top_space = (self.active_to_enable_top + self.get_line_end_space(METAL2) +
                             m2m3.height)

        # space based on enable M1 contact to power rail
        min_rail_height = self.rail_height
        en_to_vdd_top_space = active_to_poly_top + self.parallel_line_space + min_rail_height

        self.top_space = max(active_to_poly_top + poly_to_well_cont_top, en_rail_top_space,
                             en_to_vdd_top_space)

        poly_enclosure = self.implant_enclose_poly

        self.bottom_space = poly_enclosure + self.poly_extend_active
        # ensure enough space for bitlines
        min_bitline_height = 2 * self.m2_width
        self.bottom_space = max(self.bottom_space, min_bitline_height)
        # enough space for sense amp/col mux via
        self.bottom_space = max(self.bottom_space, max(m2m3.height, m3m4.height) +
                                self.get_line_end_space(METAL2) + 0.5 * self.m2_width -
                                0.5 * self.ptx_width)

        self.poly_height = (self.poly_extend_active + self.poly_top_space + self.ptx_width)
        self.poly_y_offset = max(poly_enclosure, self.bottom_space - self.poly_extend_active)

        self.height = self.bottom_space + self.ptx_width + self.top_space

        active_enclose_contact = max(drc["active_enclosure_contact"],
                                     (self.active_width - self.contact_width) / 2)
        self.poly_pitch = self.poly_width + self.poly_space
        self.end_to_poly = active_enclose_contact + self.contact_width + self.contact_to_gate

        self.active_width = 2 * self.end_to_poly + self.mults * self.poly_pitch - self.poly_space

        active_space = drc.get("active_to_body_active", drc.get("active_to_active"))

        self.ptx_active_width = self.active_width  # for actual active
        if self.width - self.active_width < active_space:
            self.active_width = self.width + 2 * 0.5 * contact.active.first_layer_width

        self.active_bot_y = self.bottom_space
        self.active_mid_y = self.active_bot_y + 0.5 * self.ptx_width
        self.active_top = self.active_bot_y + self.ptx_width

        self.poly_contact_mid_y = max(self.active_top + self.active_to_poly_cont_mid,
                                      self.active_mid_y + 0.5 * m1m2.height +
                                      self.get_line_end_space(METAL2) +
                                      0.5 * max(m1m2.width, self.en_rail_height))

        self.contact_pitch = 2 * self.contact_to_gate + self.contact_width + self.poly_width
        self.contact_space = self.contact_pitch - self.contact_width

        self.implant_height = self.height - self.well_contact_implant_height

        self.implant_width = max(self.width, self.active_width + 2 * self.implant_enclose_ptx_active)

        self.calculate_body_contacts()
        self.nwell_height = (self.contact_y + 0.5 * self.well_contact_active_height +
                             self.well_enclose_active)
        self.nwell_width = max(self.implant_width,
                               max(self.active_width, self.well_contact_active_width) +
                               2 * self.well_enclose_ptx_active)

    def create_ptx(self):
        """Initializes all the pmos"""

        # add active
        self.active_rect = self.add_rect_center("active", offset=vector(self.mid_x, self.active_mid_y),
                                                width=self.active_width, height=self.ptx_width)

        poly_x_start = self.mid_x - 0.5 * self.ptx_active_width + self.end_to_poly
        # add poly
        # poly dummys
        if "po_dummy" in tech_layers:
            self.dummy_height = max(drc["po_dummy_min_height"], self.poly_height)
            num_dummy = self.num_poly_dummies

            poly_layers = (num_dummy * ["po_dummy"] + ["poly"] * self.mults +
                           num_dummy * ["po_dummy"])
            poly_x_start -= num_dummy * self.poly_pitch
            poly_heights = (num_dummy * [self.dummy_height] + [self.poly_height] * self.mults +
                            num_dummy * [self.dummy_height])
        else:
            poly_layers = ["poly"] * self.mults
            poly_heights = [self.poly_height] * self.mults

        for i in range(len(poly_layers)):
            offset = vector(poly_x_start + i * self.poly_pitch, self.poly_y_offset)
            self.add_rect(poly_layers[i], offset=offset, height=poly_heights[i], width=self.poly_width)

        # add implant
        self.add_rect_center("pimplant", offset=vector(self.mid_x, 0.5 * self.implant_height),
                             width=self.implant_width, height=self.implant_height)

        # add nwell
        x_offset = - 0.5 * (self.nwell_width - self.width)
        self.add_rect("nwell", offset=vector(x_offset, 0), width=self.nwell_width,
                      height=self.nwell_height)

    def connect_input_gates(self):
        # adjust contact positions such that there will be space for m1 to vdd
        left_contact_mid = max(self.mid_x - self.poly_pitch,
                               0.5 * self.m1_width + self.line_end_space +
                               0.5 * contact.poly.second_layer_height)
        right_contact_mid = min(self.mid_x + self.poly_pitch,
                                self.width - 0.5 * self.m1_width - self.line_end_space -
                                0.5 * contact.poly.second_layer_height)

        gate_pos = [left_contact_mid, self.mid_x, right_contact_mid]

        for x_offset in gate_pos:
            if info["horizontal_poly"]:
                self.add_contact_center(contact.poly.layer_stack,
                                        offset=vector(x_offset, self.poly_contact_mid_y),
                                        rotate=90)
            else:
                self.add_rect_center("contact", offset=vector(x_offset, self.poly_contact_mid_y))

        offset = vector(self.mid_x, self.poly_contact_mid_y)
        via_mid_y = self.poly_contact_mid_y

        self.add_contact_center(m1m2.layer_stack, offset=vector(offset.x, via_mid_y), rotate=90)
        _, fill_width = self.calculate_min_area_fill(self.en_rail_height, layer=METAL2)
        if fill_width:
            fill_width = max(fill_width, m1m2.height)
            self.add_rect_center(METAL2, offset=vector(offset.x, via_mid_y), width=fill_width,
                                 height=self.en_rail_height)
        self.add_contact_center(m2m3.layer_stack, offset=vector(offset.x, via_mid_y), rotate=90)

        m1_poly_extension = 0.5 * contact.poly.second_layer_height
        en_m1_width = 2 * m1_poly_extension + gate_pos[2] - gate_pos[0]
        self.en_m1_rect = self.add_rect_center(METAL1, offset=offset, width=en_m1_width)

        y_offset = via_mid_y - 0.5 * self.en_rail_height
        self.add_layout_pin("en", METAL3, offset=vector(0, y_offset),
                            width=self.width, height=self.en_rail_height)

    def calculate_body_contacts(self):

        active_width, body_contact = calculate_contact_width(self, self.width,
                                                             self.well_contact_active_height)
        self.implant_width = max(self.implant_width, active_width + 2 * self.implant_enclose_active)
        self.body_contact = body_contact
        self.well_contact_active_width = active_width

        self.contact_y = self.height - 0.5 * self.well_contact_implant_height

    def add_nwell_contacts(self):
        self.add_rect_center("nimplant", offset=vector(self.mid_x, self.contact_y),
                             width=self.implant_width,
                             height=self.well_contact_implant_height)

        m1_enable_pin_top = self.poly_contact_mid_y + 0.5 * self.m1_width
        vdd_space = self.get_parallel_space(METAL1)

        vdd_pin_y = m1_enable_pin_top + vdd_space
        pin_height = self.height - vdd_pin_y
        # cover via totally with appropriate m1 but match m1 and m3 pins
        self.add_rect(METAL1, offset=vector(0, vdd_pin_y),
                      width=self.width, height=pin_height)

        # m3 pin
        m3_space = max(self.get_parallel_space(METAL3), self.get_line_end_space(METAL3))

        m3_vdd_y = self.active_top + self.active_to_enable_top + m3_space
        pin_height = self.height - m3_vdd_y
        if pin_height > self.bus_width:
            # extra space since it runs along en pin
            new_m3_space = utils.ceil(1.2 * m3_space)
            pin_height = max(self.bus_width, pin_height + utils.floor(m3_space - new_m3_space))
            m3_vdd_y = self.height - pin_height

        for layer in [METAL1, METAL3]:
            vdd_pin = self.add_layout_pin("vdd", layer, offset=vector(0, m3_vdd_y),
                                          width=self.width,
                                          height=pin_height)

        bl_br_space = self.bitcell.get_pin("br").lx() - self.bitcell.get_pin("bl").rx()
        max_via_width = bl_br_space - 2 * self.get_line_end_space(METAL2)
        num_vias = 1
        while True:
            sample_via = contact.contact(m1m2.layer_stack, dimensions=[1, num_vias])
            if sample_via.first_layer_height < max_via_width:
                num_vias += 1
            else:
                num_vias -= 1
                sample_via = contact.contact(m1m2.layer_stack, dimensions=[1, num_vias])
                break
        debug.check(num_vias >= 1, "At least one via is required")
        fill_width = sample_via.height
        _, fill_height = self.calculate_min_area_fill(fill_width, layer=METAL2)
        if fill_height > sample_via.first_layer_width:
            self.add_rect_center(METAL2, offset=vector(self.mid_x, vdd_pin.cy()),
                                 width=fill_width, height=fill_height)

        self.add_contact_center(m1m2.layer_stack, offset=vector(self.mid_x, vdd_pin.cy()),
                                size=[1, num_vias], rotate=90)
        self.add_contact_center(m2m3.layer_stack, offset=vector(self.mid_x, vdd_pin.cy()),
                                size=[1, num_vias], rotate=90)

        self.add_rect_center("active", offset=vector(self.mid_x, self.contact_y),
                             width=self.well_contact_active_width,
                             height=self.well_contact_active_height)

        self.add_contact_center(self.body_contact.layer_stack, rotate=90,
                                offset=vector(self.mid_x, self.contact_y),
                                size=self.body_contact.dimensions)

    def add_active_contacts(self):
        no_contacts = self.calculate_num_contacts(self.ptx_width)
        m1m2_contacts = max(1, no_contacts - 1)

        self.source_drain_pos = []

        self.active_contact = None

        extension = 0.5 * contact.active.first_layer_width
        mid_to_contact = 0.5 * self.poly_pitch

        x_offsets = [self.active_rect.lx() + extension,
                     self.mid_x - mid_to_contact,
                     self.mid_x + mid_to_contact,
                     self.active_rect.rx() - extension]

        for i in range(4):
            offset = vector(x_offsets[i], self.active_mid_y)
            self.source_drain_pos.append(offset.x)
            self.active_contact = self.add_contact_center(layers=contact.contact.active_layers,
                                                          size=[1, no_contacts], offset=offset)

            if i in [0, 3]:
                if i == 0:
                    target_x = min(0, self.en_m1_rect.lx() - self.line_end_space - self.m1_width)
                else:
                    target_x = max(self.width - self.m1_width,
                                   self.en_m1_rect.rx() + self.line_end_space)
                self.add_rect(METAL1, offset=offset - vector(0.5 * self.m1_width, 0),
                              height=self.active_top - offset.y)
                y_offset = self.active_top - self.m1_width
                self.add_rect(METAL1, offset=vector(target_x, y_offset),
                              width=offset.x - target_x)
                self.add_rect(METAL1, offset=vector(target_x, y_offset),
                              height=self.contact_y - y_offset)
            else:
                self.add_contact_center(layers=contact.contact.m1m2_layers,
                                        size=[1, m1m2_contacts], offset=offset)

    def connect_bitlines(self):

        pin_names = ["bl", "br"]
        x_offsets = [self.source_drain_pos[1], self.source_drain_pos[2]]
        for i in range(2):
            bitcell_pin = self.bitcell.get_pin(pin_names[i])
            pin = self.add_layout_pin(pin_names[i], METAL2, offset=vector(bitcell_pin.lx(), 0),
                                      height=self.height, width=bitcell_pin.width())
            self.add_rect(METAL2, offset=vector(pin.cx(), self.active_mid_y - 0.5 * self.m2_width),
                          width=x_offsets[i] - pin.cx())

    def add_ptx_inst(self):
        """Adds both the upper_pmos and lower_pmos to the module"""

        self.pmos = ptx_spice(tx_type="pmos",
                              width=self.ptx_width, mults=1)
        self.add_inst(name="equalizer_pmos", mod=self.pmos, offset=vector(0, 0))
        self.connect_inst(["bl", "en", "br", "vdd"])
        self.add_inst(name="bl_pmos", mod=self.pmos, offset=vector(0, 0))
        self.connect_inst(["bl", "en", "vdd", "vdd"])
        self.add_inst(name="br_pmos", mod=self.pmos, offset=vector(0, 0))
        self.connect_inst(["br", "en", "vdd", "vdd"])

    def drc_fill(self):

        min_area = self.get_min_area(METAL1)
        min_height = min_area / self.m1_width
        if self.active_contact.height > min_height:
            return

        fill_width = self.poly_pitch - self.get_parallel_space(METAL1)
        fill_height = utils.ceil(min_area / fill_width)
        fill_height = max(fill_height, 0.5 * self.ptx_width + 0.5 * self.active_contact.height)
        fill_width = max(self.active_contact.width, utils.ceil(min_area / fill_height))

        fill_indices = [1, 2]
        for i in range(2):
            x_offset = self.source_drain_pos[fill_indices[i]] - 0.5 * fill_width
            y_offset = self.active_top - fill_height
            self.add_rect("metal1", offset=vector(x_offset, y_offset),
                          width=fill_width, height=fill_height)


class precharge_tap(design.design, metaclass=Unique):
    @classmethod
    def get_name(cls, precharge_cell, name=None):
        name = name or f"precharge_tap_{precharge_cell.name}_{precharge_cell.size:.3g}"
        return name

    def __init__(self, precharge_cell: precharge, name=None):
        design.design.__init__(self, self.get_name(precharge_cell, name))

        self.height = precharge_cell.height
        self.precharge_cell = precharge_cell

        self.create_layout()
        add_tech_layers(self)
        self.add_boundary()

    def create_layout(self):
        body_tap = self.create_mod_from_str_(OPTS.body_tap)
        self.width = body_tap.width

        self.vdd_rail = vdd_rail = (utils.get_libcell_pins(["vdd"],
                                                           body_tap.gds_file)["vdd"][0])

        all_precharge_vdd = self.precharge_cell.get_pins("vdd")
        self.precharge_vdd = precharge_vdd = next(x for x in all_precharge_vdd
                                                  if x.layer == METAL3)
        self.add_rect(METAL3, offset=vector(0, precharge_vdd.by()), width=self.width,
                      height=precharge_vdd.height())
        en_pin = self.precharge_cell.get_pin("en")

        max_via_height = precharge_vdd.uy() - en_pin.uy() - self.get_parallel_space(METAL2)
        num_vias = 1
        while True:
            sample_contact = contact.contact(m1m2.layer_stack, dimensions=[1, num_vias])
            if sample_contact.height > max_via_height:
                num_vias -= 1
                sample_contact = contact.contact(m1m2.layer_stack, dimensions=[1, num_vias])
                break
            num_vias += 1

        self.add_rect(vdd_rail.layer, offset=vector(vdd_rail.lx(), 0), width=vdd_rail.width(),
                      height=self.height)
        via_offset = vector(vdd_rail.cx() - 0.5 * m1m2.second_layer_width,
                            precharge_vdd.uy() - sample_contact.second_layer_height)
        m1m2_cont = self.add_contact(m1m2.layer_stack, offset=via_offset, size=[1, num_vias])
        self.add_contact(m2m3.layer_stack, offset=via_offset, size=[1, num_vias])
        self.add_contact(m3m4.layer_stack, offset=via_offset, size=[1, num_vias])
        fill_height, fill_width = self.calculate_min_area_fill(m1m2_cont.height, layer=METAL2)
        self.add_rect(METAL2, offset=vector(vdd_rail.cx() - 0.5 * fill_width, via_offset.y),
                      width=fill_width, height=fill_height)

        # tap nimplant
        nimp_rects = self.precharge_cell.get_layer_shapes(NIMP)
        if not nimp_rects:
            self.add_well_tap()
            return
        nimp_rect = max(nimp_rects, key=lambda x: x.uy())
        self.add_rect(NIMP, offset=vector(nimp_rect.lx(), nimp_rect.by()),
                      width=self.width + (nimp_rect.rx() - self.precharge_cell.width) -
                            nimp_rect.lx(), height=nimp_rect.height)

    def add_well_tap(self):
        bitcell_tap = self.create_mod_from_str_(OPTS.body_tap)
        bitcell_active = bitcell_tap.get_layer_shapes(TAP_ACTIVE)
        if bitcell_active:
            mid_x = bitcell_active[0].cx()
            tap_width = bitcell_active[0].width
            tap_height = bitcell_active[0].height
        else:
            mid_x = 0.5 * self.width
            tap_width = self.get_min_layer_width(TAP_ACTIVE)
            _, tap_height = self.calculate_min_area_fill(tap_width, layer=TAP_ACTIVE)
        # make sample contact
        sample_contact = calculate_num_contacts(self, tap_height, return_sample=True,
                                                layer_stack=well_contact.layer_stack)

        all_nwell = self.precharge_cell.get_layer_shapes(NWELL)
        if not all_nwell:
            offset = vector(mid_x, 0.5 * self.height)
            implant_layer = PIMP
        else:
            nwell = max(all_nwell, key=lambda x: x.height * x.width)
            offset = vector(mid_x, nwell.cy())
            implant_layer = NIMP

        contact_active = sample_contact.get_layer_shapes(TAP_ACTIVE)[0]

        real_cont = self.add_contact_center(sample_contact.layer_stack, offset,
                                            size=sample_contact.dimensions)
        tap_width = max(tap_width, contact_active.width)
        tap_height = max(tap_height, contact_active.height)
        self.add_rect_center(TAP_ACTIVE, offset, width=tap_width, height=tap_height)
        # add implants
        bitcell_implant = bitcell_tap.get_layer_shapes(PIMP)[0]
        implant_width = max(tap_width + 2 * self.implant_enclose_active,
                            bitcell_implant.width)

        _, implant_height = self.calculate_min_area_fill(implant_width, layer=NIMP)
        implant_height = max(tap_height + 2 * self.implant_enclose_active, implant_height)

        self.add_rect_center(implant_layer, offset, width=implant_width,
                             height=implant_height)
        self.join_m1_vdd(real_cont)

    def join_m1_vdd(self, well_cont):
        # join m1 to vdd
        x_offset = self.vdd_rail.cx() - 0.5 * self.m1_width
        m1_rect = well_cont.get_layer_shapes(METAL1)[0]
        self.add_rect(METAL1, vector(x_offset, m1_rect.by()),
                      width=m1_rect.cx() - x_offset, height=m1_rect.height)
        self.add_rect(METAL1, vector(x_offset, m1_rect.by()),
                      height=self.precharge_vdd.cy() - m1_rect.by())
