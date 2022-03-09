from base import contact
from base.contact import m2m3, m1m2
from base.design import ACTIVE, NIMP, PIMP, NWELL, PWELL, METAL1, POLY, METAL3, METAL2, PO_DUMMY, design
from base.vector import vector
from base.well_active_contacts import get_max_contact
from base.well_implant_fills import calculate_tx_metal_fill
from globals import OPTS
from modules.horizontal.pgate_horizontal import pgate_horizontal


class wordline_pgate_horizontal(pgate_horizontal):
    max_num_fingers = None
    pgate_name = "pgate"
    nmos_pmos_nets_aligned = False  # nmos and pmos nets directly connected

    def get_source_drain_connections(self):
        # [(nmos_power, pmos_power), (nmos_outputs, pmos_outputs)]
        raise NotImplementedError

    @classmethod
    def get_name(cls, size=1, beta=None, mirror=False):
        beta, beta_suffix = cls.get_beta(beta, size)
        mirror_suffix = "_mirror" * mirror
        name = "{}_{:.3g}{}{}".format(cls.pgate_name, size, beta_suffix, mirror_suffix) \
            .replace(".", "__")
        return name

    def __init__(self, size=1, beta=None, mirror=False):
        self.mirror = mirror
        super().__init__(size, beta)

    @classmethod
    def initialize_constraints(cls, design_self: 'pgate_horizontal'):
        super().initialize_constraints(design_self)
        cls.bitcell = design_self.create_mod_from_str(OPTS.bitcell)
        poly_rects = cls.bitcell.get_layer_shapes(POLY)

        longest_poly = max(poly_rects, key=lambda x: max(x.width, x.height))

        cls.poly_width = min(longest_poly.height, longest_poly.width)
        cls.poly_pitch = cls.poly_width + design_self.poly_space

        cls.max_num_fingers = len(poly_rects)

        active_rects = cls.bitcell.get_layer_shapes(ACTIVE)
        # find active rects with poly overlap
        active_rects = [active_rect for active_rect in active_rects if
                        any([poly_rect.overlaps(active_rect) for poly_rect in poly_rects])]
        top_active = max(active_rects, key=lambda x: x.uy())
        bottom_active = min(active_rects, key=lambda x: x.by())
        cls.bitcell_top_overlap = top_active.uy() >= cls.bitcell.height
        cls.bitcell_bot_overlap = bottom_active.by() <= 0

    def calculate_fills(self, nmos_width, pmos_width):

        # TODO fix non-default pitch messes up fill calculations
        # Fix fill calculation to take min-width into account
        original_pitch = self.poly_pitch
        self.poly_pitch = contact.poly.poly_pitch
        self.nmos_fill = calculate_tx_metal_fill(nmos_width, self)
        self.pmos_fill = calculate_tx_metal_fill(pmos_width, self)
        self.poly_pitch = original_pitch

    def get_poly_y_offsets(self, num_fingers):
        return [self.poly_y + i * self.poly_pitch for i in range(num_fingers)], [], []

    def get_source_drain_offsets(self):
        return [i * self.poly_pitch for i in range(self.num_fingers + 1)]

    def add_poly_and_active(self, active_widths):
        self.poly_x_offset = max(self.implant_enclose_poly,
                                 0.5 * (contact.poly.second_layer_height -
                                        contact.poly.first_layer_height))

        poly_to_mid_contact = 0.5 * contact.poly.first_layer_height

        self.gate_contact_x = (self.poly_x_offset + poly_to_mid_contact
                               - 0.5 * self.contact_width)
        self.pin_right_x = (self.gate_contact_x + 0.5 * self.contact_width +
                            0.5 * contact.poly.second_layer_height)

        self.n_active_x = self.pin_right_x + self.get_line_end_space(METAL1)

        contact_height = max(contact.active.height, contact.m1m2.height)
        if self.nmos_finger_width < contact_height:
            self.n_active_x += 0.5 * (contact_height - self.nmos_finger_width)

        if self.mirror:
            finger_width = self.pmos_finger_width
        else:
            finger_width = self.nmos_finger_width

        self.n_active_right = self.n_active_x + finger_width

        self.active_rect_space = 2 * max(self.implant_enclose_ptx_active,
                                         self.well_enclose_active, 0.5 * self.poly_space)

        if not self.nmos_pmos_nets_aligned:
            self.active_rect_space = (max(0, 0.5 * (m1m2.height - self.nmos_finger_width)) +
                                      2 * self.get_line_end_space(METAL1) + self.m1_width +
                                      max(0, 0.5 * (m1m2.height - self.pmos_finger_width)))

        self.p_active_x = self.n_active_right + self.active_rect_space

        if self.mirror:
            temp = self.p_active_x
            self.p_active_x = self.n_active_x
            self.n_active_x = temp
            self.n_active_right = temp + self.nmos_finger_width

        self.p_active_right = self.p_active_x + self.pmos_finger_width

        self.active_height = ((self.num_fingers - 1) * self.poly_pitch
                              + self.poly_width + 2 * self.active_to_poly)

        self.poly_y = 0.5 * self.poly_space
        self.active_y = self.poly_y - self.active_to_poly

        x_offsets = [(self.n_active_x, self.n_active_right),
                     (self.p_active_x, self.p_active_right)]
        active_rects = []
        for left, right in x_offsets:
            active_rects.append(self.add_rect(ACTIVE, offset=vector(left, self.active_y),
                                              width=right - left, height=self.active_height))
        self.nmos_active, self.pmos_active = active_rects
        active_rects = list(sorted(self.get_layer_shapes(ACTIVE), key=lambda x: x.lx()))
        self.left_active_rect, self.right_active_rect = active_rects

        self.poly_right_x = self.right_active_rect.rx() + self.poly_extend_active
        y_offset = self.poly_y
        for i in range(self.num_fingers):
            self.add_rect(POLY, offset=vector(self.poly_x_offset, y_offset),
                          width=self.poly_right_x - self.poly_x_offset,
                          height=self.poly_width)
            y_offset += self.poly_pitch

        m1_extension = max(0, 0.5 * (m1m2.height - self.right_active_rect.width))
        self.output_x = (self.right_active_rect.rx() + m1_extension +
                         self.get_line_end_space(METAL1))

        self.width = max(self.poly_right_x + self.implant_enclose_poly,
                         self.poly_right_x + self.poly_vert_space - self.implant_enclose_poly,
                         self.output_x +
                         self.m1_width + self.get_line_end_space(METAL1))
        self.height = self.bitcell.height

    def add_implants_and_nwell(self):

        active_rects = [self.left_active_rect, self.right_active_rect]

        y_enclosures = [self.implant_enclose_ptx_active, self.well_enclose_ptx_active]

        implant_layers = [NIMP, PIMP]
        well_layers = [PWELL, NWELL]

        m1m2_extension = max(0, 0.5 * (m1m2.height - self.left_active_rect.width))
        self.mid_x = self.left_active_rect.rx() + max(0.5 * self.active_rect_space,
                                                      m1m2_extension +
                                                      self.get_line_end_space(METAL1) +
                                                      0.5 * self.m1_width)

        for type_index, layer_type in enumerate([implant_layers, well_layers]):
            if self.mirror:
                layer_type = list(reversed(layer_type))
            for layer_index, layer in enumerate(layer_type):
                if layer == PWELL and not self.has_pwell:
                    continue

                active_rect = active_rects[layer_index]

                if layer_index == 0:
                    rect_x = 0
                    rect_right = self.mid_x
                else:
                    rect_right = self.width
                    rect_x = self.mid_x

                rect_bottom = active_rect.by() - y_enclosures[type_index]
                rect_top = max(active_rect.uy() + y_enclosures[type_index],
                               self.height)
                self.add_rect(layer, offset=vector(rect_x, rect_bottom),
                              width=rect_right - rect_x,
                              height=rect_top - rect_bottom)

    def connect_outputs(self):
        # join output connections
        _, (nmos_conns, pmos_conns) = self.get_source_drain_connections()
        y_offsets = [x - 0.5 * self.m1_width for x in self.get_source_drain_offsets()]

        if nmos_conns == pmos_conns:
            for y_index in nmos_conns:
                self.add_rect(METAL1, offset=vector(self.nmos_active.cx(), y_offsets[y_index]),
                              width=self.pmos_active.cx() - self.nmos_active.cx())
        else:
            top_y = y_offsets[max(nmos_conns + pmos_conns)] + self.m1_width
            bot_y = y_offsets[min(nmos_conns + pmos_conns)]
            self.add_rect(METAL1, offset=vector(self.mid_x - 0.5 * self.m1_width, bot_y),
                          width=self.m1_width, height=top_y - bot_y)
            for rect, conns in [(self.nmos_active, nmos_conns), (self.pmos_active, pmos_conns)]:
                for y_index in conns:
                    self.add_rect(METAL1, offset=vector(self.mid_x, y_offsets[y_index]),
                                  width=rect.cx() - self.mid_x)
        # output pin
        x_offset = self.output_x
        conns = pmos_conns if self.pmos_active == self.right_active_rect else nmos_conns
        for y_index in conns:
            self.add_rect(METAL1, offset=vector(x_offset, y_offsets[y_index]),
                          width=self.right_active_rect.cx() - x_offset)

        top_y = y_offsets[max(conns)] + self.m1_width
        bot_y = y_offsets[min(conns)]

        self.add_layout_pin("Z", METAL1, offset=vector(x_offset, bot_y),
                            height=top_y - bot_y)

    def connect_power(self):

        conn_indices, _ = self.get_source_drain_connections()
        y_offsets = self.get_source_drain_offsets()

        pin_names = ["gnd", "vdd"]
        actives = [self.nmos_active, self.pmos_active]
        via_shift = 0.5 * (m2m3.height - contact.active.height)
        for i in range(2):
            pin_name = pin_names[i]

            x_offset = actives[i].cx() + via_shift

            contact_dimensions = get_max_contact(m2m3.layer_stack, actives[i].width).dimensions
            num_contacts = min(2, contact_dimensions[1])

            pin = self.get_pin(pin_name)
            self.add_contact_center(m2m3.layer_stack, offset=vector(x_offset, pin.cy()),
                                    rotate=90, size=[1, num_contacts])

            self.add_rect_center(METAL2, offset=vector(x_offset, 0.5 * self.height),
                                 width=m1m2.height, height=self.height)

    def add_power_pins(self, layer=METAL3):
        if "gnd" in self.bitcell.pin_map:
            self.rail_height = self.bitcell.get_pins("gnd")[0].height()

        super().add_power_pins(layer)

    def add_contact_fills(self):
        fill_props = ["nmos_fill", "pmos_fill"]
        active_rects = [self.nmos_active, self.pmos_active]
        conn_indices, _ = self.get_source_drain_connections()

        y_offsets = self.get_source_drain_offsets()

        for i in range(2):
            active_rect = active_rects[i]
            contact_dimensions = get_max_contact(m1m2.layer_stack, active_rect.width).dimensions

            if getattr(self, fill_props[i]):
                fill_x, fill_right, fill_height, fill_width = getattr(self, fill_props[i])
                real_fill_x = fill_x + active_rects[i].lx()
                for y_index in conn_indices[i]:
                    y_offset = y_offsets[y_index] - 0.5 * fill_height
                    self.add_rect(METAL1, offset=vector(real_fill_x, y_offset),
                                  width=fill_width, height=fill_height)
                m1m2_via_x = fill_x + active_rect.lx() + 0.5 * contact.m1m2.height
            else:
                m1m2_via_x = active_rect.cx()
            for y_index in conn_indices[i]:
                self.add_contact_center(m1m2.layer_stack, size=contact_dimensions,
                                        offset=vector(m1m2_via_x, y_offsets[y_index]),
                                        rotate=90)

    @classmethod
    def get_dummy_y_offsets(cls, reference_mod: "wordline_pgate_horizontal"):
        poly_rects = reference_mod.get_layer_shapes(POLY)
        top_rect = max(poly_rects, key=lambda x: x.uy())
        bottom_rect = min(poly_rects, key=lambda x: x.by())
        poly_pitch = reference_mod.poly_pitch

        return ([bottom_rect.by() - i * poly_pitch for i in range(2, 0, -1)],
                [top_rect.uy() + i * poly_pitch for i in range(1, 3)])

    @staticmethod
    def create_dummies(parent_mod: design, top_y, bottom_y, reference_mod=None):
        if reference_mod is None:
            reference_mod = parent_mod
        if not reference_mod.insert_poly_dummies:
            return
        bottom_offsets, top_offsets = reference_mod.get_dummy_y_offsets(reference_mod)
        bottom_offsets = [x + bottom_y for x in bottom_offsets]
        top_offsets = [x + top_y for x in top_offsets]

        dummy_enclosure = 0.5 * parent_mod.poly_to_field_poly
        for y_offset in bottom_offsets + top_offsets:
            parent_mod.add_rect(PO_DUMMY, offset=vector(dummy_enclosure, y_offset),
                                width=parent_mod.width - 2 * dummy_enclosure,
                                height=reference_mod.poly_width)
