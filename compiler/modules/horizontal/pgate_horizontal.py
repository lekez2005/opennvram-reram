import math

import tech
from base import utils, contact
from base.contact import m1m2
from base.design import design, METAL1, PO_DUMMY, ACTIVE, POLY, PIMP, NIMP, NWELL, METAL2, CONTACT, PWELL
from base.hierarchy_layout import GDS_ROT_90
from base.vector import vector
from base.well_implant_fills import calculate_tx_metal_fill
from pgates.pgates_characterization_base import pgates_characterization_base
from pgates.ptx_spice import ptx_spice
from tech import drc, parameter, layer as tech_layers


class pgate_horizontal(pgates_characterization_base, design):
    rotation_for_drc = GDS_ROT_90
    contraints_initialized = False
    num_instances = 1
    instances_mod = None
    max_tx_mults = 3  # to support  3 input NAND
    num_fingers = 1
    all_nmos = True
    all_pmos = True
    num_poly_contacts = 1

    nmos_finger_width = pmos_finger_width = rail_height = height = None

    def __init__(self, size=1, beta=None):
        beta, beta_suffix = self.get_beta(beta, size)
        self.beta = beta
        self.size = size
        design.__init__(self, self.name)
        if not pgate_horizontal.contraints_initialized:
            self.__class__.initialize_constraints(self)
        self.rail_height = self.__class__.rail_height
        self.height = self.__class__.height

        self.create_layout()

    @staticmethod
    def get_beta(beta, size):
        # TODO beta based on size
        if hasattr(tech, "calculate_beta"):
            default_beta = tech.calculate_beta(size)
        else:
            default_beta = parameter["beta"]
        if beta is None:
            beta = default_beta

        if not beta == default_beta:
            beta_suffix = "_b" + str(beta)
        else:
            beta_suffix = ""
        return beta, beta_suffix

    # Abstract methods
    def add_pins(self):
        raise NotImplementedError

    def calculate_constraints(self):
        raise NotImplementedError

    def get_ptx_connections(self):
        raise NotImplementedError

    def add_ptx_insts(self):
        offset = vector(0, 0)
        self.pmos = ptx_spice(self.pmos_finger_width,
                              mults=int(self.num_fingers / self.num_poly_contacts),
                              tx_type="pmos")
        self.add_mod(self.pmos)
        self.nmos = ptx_spice(self.nmos_finger_width,
                              mults=int(self.num_fingers / self.num_poly_contacts),
                              tx_type="nmos")
        for index, conn_def in enumerate(self.get_ptx_connections()):
            mos, conn = conn_def
            name = "{}{}".format(mos.tx_type, index + 1)
            self.add_inst(name=name, mod=mos, offset=offset)
            self.connect_inst(conn)

    def create_layout(self):
        self.add_pins()
        self.calculate_constraints()
        self.instances_mod = self

        active_widths = [self.nmos_finger_width, self.pmos_finger_width]

        self.calculate_fills(self.nmos_finger_width, self.pmos_finger_width)

        self.add_poly_and_active(active_widths=active_widths)
        self.add_implants_and_nwell()

        self.add_technology_specific_layers()
        self.add_active_contacts()
        self.add_contact_fills()

        self.connect_inputs()

        self.connect_outputs()
        self.add_power_pins()
        self.connect_power()

        self.add_ptx_insts()
        self.add_boundary()

    @classmethod
    def initialize_constraints(cls, design_self: 'pgate_horizontal'):
        rail_height = design_self.rail_height

        active_enclose_contact = max(drc["active_enclosure_contact"],
                                     (design_self.active_width - design_self.contact_width) / 2)

        cls.active_enclosure_contact = active_enclose_contact

        cls.insert_poly_dummies = PO_DUMMY in tech_layers

        cls.active_y = utils.round_to_grid(0.5 * rail_height) + cls.get_parallel_space(METAL1)

        cls.active_to_poly = (active_enclose_contact + design_self.contact_width
                              + design_self.contact_to_gate)

        first_poly_y = cls.active_y + cls.active_to_poly

        # if dummy present
        first_dummy_poly_y = 0

        if cls.insert_poly_dummies:
            # first assume no dummy at y = 0, put first dummy at the dummy space
            first_dummy_poly_y = utils.round_to_grid(0.5 * design_self.poly_space)
            first_real_poly_y = first_dummy_poly_y + design_self.poly_pitch
            if first_real_poly_y < first_poly_y:
                # need to add a dummy at y = 0
                first_dummy_poly_y = - 0.5 * design_self.poly_width
                first_poly_y = first_dummy_poly_y + 2 * design_self.poly_pitch
            else:
                first_poly_y = first_real_poly_y

            cls.active_y = first_poly_y - cls.active_to_poly
            rail_top = cls.active_y - cls.get_parallel_space(METAL1)

            cls.rail_height = utils.round_to_grid(2 * rail_top)
        else:
            cls.rail_height = rail_height
        if "max_rail_height" in drc:
            cls.rail_height = min(drc["max_rail_height"], cls.rail_height)

        cls.n_active_y = cls.active_y

        active_height = ((cls.max_tx_mults - 1) * design_self.poly_pitch
                         + design_self.poly_width + 2 * cls.active_to_poly)

        cls.n_active_top = cls.n_active_y + active_height

        cls.p_active_y = cls.n_active_top + 2 * design_self.well_enclose_active

        if cls.insert_poly_dummies:
            # poly grid needs to be maintained
            # assumes we add two dummies in between the two actives
            pmos_poly_y = (cls.n_active_top - cls.active_to_poly - design_self.poly_width
                           + 3 * design_self.poly_pitch)
            cls.p_active_y = pmos_poly_y - cls.active_to_poly
        cls.p_active_top = cls.p_active_y + active_height

        cls.mid_y = 0.5 * (cls.n_active_top + cls.p_active_y)

        # same space above pmos active as below nmos active
        cls.height = cls.p_active_top + cls.n_active_y

        # calculate real poly positions
        cls.n_poly_offsets = [cls.n_active_y + cls.active_to_poly +
                              i * design_self.poly_pitch for i in range(cls.max_tx_mults)]
        cls.p_poly_offsets = [cls.p_active_y + cls.active_to_poly +
                              i * design_self.poly_pitch for i in range(cls.max_tx_mults)]

        # calculate dummy y positions
        cls.dummy_poly_offsets = []
        if cls.insert_poly_dummies:
            all_real_poly_y = [utils.round_to_grid(x)
                               for x in cls.n_poly_offsets + cls.p_poly_offsets]
            y_offset = first_dummy_poly_y
            while y_offset < (cls.height - first_dummy_poly_y):
                y_offset = utils.round_to_grid(y_offset)
                if y_offset not in all_real_poly_y:
                    cls.dummy_poly_offsets.append(y_offset)
                y_offset += design_self.poly_pitch

        cls.contraints_initialized = True

    def calculate_fills(self, nmos_width, pmos_width):
        self.nmos_fill = self.num_fingers > 1 and calculate_tx_metal_fill(nmos_width, self)
        self.pmos_fill = self.num_fingers > 1 and calculate_tx_metal_fill(pmos_width, self)

    def get_poly_y_offsets(self, num_fingers):
        pmos_offsets = []
        nmos_offsets = []
        dummy_offsets = []
        start_index = int(math.floor(len(self.n_poly_offsets) / 2))
        poly_indices = []
        for i in range(num_fingers):
            if i % 2 == 0:
                index = start_index - int(i / 2)
            else:
                index = start_index + math.ceil(i / 2)
            poly_indices.append(index)
        for i in range(len(self.n_poly_offsets)):
            if i in poly_indices:
                pmos_offsets.append(self.p_poly_offsets[i])
                nmos_offsets.append(self.n_poly_offsets[i])
            else:
                dummy_offsets.append(self.p_poly_offsets[i])
                dummy_offsets.append(self.n_poly_offsets[i])
        dummy_offsets += self.dummy_poly_offsets
        return nmos_offsets, pmos_offsets, dummy_offsets

    def add_poly_and_active(self, active_widths):
        num_fingers = self.num_fingers
        nmos_poly_offsets, pmos_poly_offsets, dummy_offsets = self.get_poly_y_offsets(num_fingers)

        self.nmos_poly_offsets = nmos_poly_offsets
        self.pmos_poly_offsets = pmos_poly_offsets

        poly_to_mid_contact = 0.5 * contact.poly.first_layer_height

        input_x_offset = max(self.get_parallel_space(METAL1),
                             self.get_via_space(m1m2))

        if self.num_poly_contacts == 1:
            # inverter
            poly_x_offset = max(input_x_offset + 0.5 * self.m1_width -
                                0.5 * contact.poly.first_layer_height,
                                0.5 * self.poly_to_field_poly)
            gate_contact_x = poly_x_offset + poly_to_mid_contact - 0.5 * self.contact_width
            pin_right_x = (gate_contact_x + 0.5 * self.contact_width +
                           0.5 * max(self.m1_width, self.m2_width))
        else:
            pitch = max(self.m1_width + self.get_parallel_space(METAL1),
                        self.m2_width + self.get_parallel_space(METAL2))

            for _ in range(self.num_poly_contacts - 1):
                input_x_offset += pitch
            # for nand and nor, A pin is wide enough to prevent line end space drc issue
            self.nand_nor_pin_width = max(self.get_drc_by_layer(METAL1,
                                                                "line_end_threshold") or 0.0,
                                          self.m2_width)
            poly_m1_extension = 0.5 * self.m1_width + 0.5 * contact.poly.second_layer_height
            pin_right_x = max(input_x_offset + self.nand_nor_pin_width,
                              input_x_offset + poly_m1_extension)

            m1_poly_x_extension = 0.5 * (self.m1_width - self.contact_width)
            gate_contact_x = min(pin_right_x - self.nand_nor_pin_width + m1_poly_x_extension,
                                 input_x_offset + 0.5 * self.m1_width - 0.5 * self.contact_width)

            poly_x_offset = gate_contact_x + 0.5 * self.contact_width - poly_to_mid_contact

        self.gate_contact_x = gate_contact_x
        self.pin_right_x = pin_right_x

        self.poly_x_offset = poly_x_offset

        m1_extension = max(0, 0.5 * (m1m2.first_layer_height - min(active_widths)))
        m2_extension = max(0, 0.5 * (m1m2.second_layer_height - min(active_widths)))

        active_x = max(pin_right_x + m1_extension + self.get_line_end_space(METAL1),
                       pin_right_x + m2_extension + self.get_parallel_space(METAL2))

        all_poly_y_offsets = [nmos_poly_offsets, pmos_poly_offsets]

        active_height = ((num_fingers - 1) * self.poly_pitch
                         + self.poly_width + 2 * self.active_to_poly)

        max_poly_width = 0
        active_rects = []

        for i in range(2):
            # add active
            poly_y_offsets = all_poly_y_offsets[i]
            active_y = min(poly_y_offsets) - self.active_to_poly

            active_rect = self.add_rect(ACTIVE, offset=vector(active_x, active_y),
                                        width=active_widths[i],
                                        height=active_height)
            active_rects.append(active_rect)

            # add poly
            poly_width = active_x - poly_x_offset + active_widths[i] + self.poly_extend_active
            for y_offset in poly_y_offsets:
                self.add_rect(POLY, offset=vector(poly_x_offset, y_offset),
                              width=poly_width, height=self.poly_width)

            max_poly_width = max(max_poly_width, poly_width)
        self.nmos_active, self.pmos_active = active_rects

        # width based on poly
        if self.insert_poly_dummies:
            dummy_min_height = drc["po_dummy_min_height"]
            width_by_dummy = dummy_min_height + self.poly_to_field_poly
        else:
            dummy_min_height = 0
            width_by_dummy = 0
        width_by_poly = poly_x_offset + max_poly_width + 0.5 * self.poly_to_field_poly
        self.poly_right_x = poly_x_offset + max_poly_width
        # width based on output pin
        output_x = 0.0
        if self.pmos_fill:
            x_offset, fill_right, fill_height, fill_width = self.pmos_fill
            output_x = (max(self.pmos_active.lx() + fill_right, self.pmos_active.rx())
                        + self.get_line_end_space(METAL1))
        if self.nmos_fill:
            x_offset, fill_right, fill_height, fill_width = self.nmos_fill
            output_x = max(output_x, max(self.nmos_active.lx() + fill_right, self.nmos_active.rx())
                           + self.get_line_end_space(METAL1))
        if not self.pmos_fill and not self.nmos_fill:
            output_x = (max(self.nmos_active.rx(), self.pmos_active.rx())
                        + self.get_line_end_space(METAL1))
        self.output_x = output_x

        width_by_output = self.output_x + self.m1_width

        self.width = max(width_by_poly, width_by_output, width_by_dummy)
        self.output_x = self.width - self.m1_width

        if self.insert_poly_dummies:
            # add dummies
            if max_poly_width < dummy_min_height:
                poly_x_offset = 0.5 * self.poly_to_field_poly
                dummy_width = dummy_min_height
            else:
                dummy_width = max_poly_width
            if self.insert_poly_dummies:
                for y_offset in dummy_offsets:
                    self.add_rect(PO_DUMMY, offset=vector(poly_x_offset, y_offset),
                                  height=self.poly_width, width=dummy_width)
            self.poly_right_x = max(self.poly_right_x, poly_x_offset + dummy_width)

    def add_implants_and_nwell(self):
        # implants
        implant_enclose_poly = self.implant_enclose_poly
        implant_x = min(self.poly_x_offset - implant_enclose_poly, 0)
        implant_right = max(self.width, self.poly_right_x + implant_enclose_poly)
        y_offsets = [0.0, self.mid_y]
        heights = [self.mid_y, self.height - self.mid_y]
        implant_layers = [NIMP, PIMP]
        for i in range(2):
            self.add_rect(implant_layers[i], offset=vector(implant_x, y_offsets[i]),
                          width=implant_right - implant_x, height=heights[i])

        # nwell
        nwell_x = implant_x
        self.add_rect(NWELL, offset=vector(nwell_x, self.mid_y),
                      width=self.width - nwell_x - nwell_x,
                      height=self.height - self.mid_y)
        if self.has_pwell:
            self.add_rect(PWELL, offset=vector(nwell_x, 0),
                          width=self.width - nwell_x - nwell_x,
                          height=self.mid_y)

    def get_contact_indices(self, is_nmos):
        if (is_nmos and self.all_nmos) or (not is_nmos and self.all_pmos):
            all_indices = range(self.num_fingers + 1)
        else:
            # only connect first and last
            all_indices = [0, self.num_fingers]
        return all_indices

    def get_output_indices(self, is_nmos):
        all_indices = self.get_contact_indices(is_nmos)
        if is_nmos:
            return list(filter(lambda x: x % 2 == 1, all_indices))
        else:
            if self.num_fingers % 2 == 1:
                return list(filter(lambda x: x % 2 == 0, all_indices))
            else:
                return list(filter(lambda x: x % 2 == 1, all_indices))

    def get_power_indices(self, is_nmos):
        all_indices = self.get_contact_indices(is_nmos)
        if is_nmos:
            return list(filter(lambda x: x % 2 == 0, all_indices))
        else:
            if self.num_fingers % 2 == 1:
                return list(filter(lambda x: x % 2 == 1, all_indices))
            else:
                return list(filter(lambda x: x % 2 == 0, all_indices))

    def get_contact_mid_y(self, contact_index, is_nmos):
        active_rect = self.nmos_active if is_nmos else self.pmos_active
        contact_y = (active_rect.by() + self.active_enclosure_contact
                     + contact_index * self.poly_pitch)
        return contact_y + 0.5 * self.contact_width

    def add_active_contacts(self):

        active_rects = [self.nmos_active, self.pmos_active]
        for i in range(2):
            active_rect = active_rects[i]
            num_contacts = self.calculate_num_contacts(active_rect.width)
            if i == 0:
                self.nmos_contacts = num_contacts
            else:
                self.pmos_contacts = num_contacts

            all_indices = self.get_contact_indices(is_nmos=i == 0)

            for j in all_indices:
                y_offset = active_rect.by() + self.active_enclosure_contact + j * self.poly_pitch
                x_offset = active_rect.lx() + 0.5 * active_rect.width
                self.add_contact_center(contact.active.layer_stack,
                                        offset=vector(x_offset,
                                                      y_offset + 0.5 * self.contact_width),
                                        size=(1, num_contacts), rotate=90)

    def add_contact_fills(self):
        num_fingers = self.num_fingers
        active_rects = [self.nmos_active, self.pmos_active]
        for i in range(2):
            is_nmos = i == 0
            is_pmos = not is_nmos

            all_indices = self.get_power_indices(is_nmos=is_nmos)

            if is_nmos and self.nmos_fill:
                fill_x, _, fill_height, fill_width = self.nmos_fill
            elif is_pmos and self.pmos_fill:
                fill_x, _, fill_height, fill_width = self.pmos_fill
            else:
                fill_x = fill_height = fill_width = None

            active_rect = active_rects[i]

            if self.num_fingers > 1 and len(all_indices) > 1:

                # Add m1 to m2 via
                num_contacts = max(1, self.calculate_num_contacts(active_rect.width) - 1)

                m1_m2_contact_x = None
                for index in all_indices:
                    y_offset = self.get_contact_mid_y(index, is_nmos=is_nmos)
                    if fill_x is None:
                        m1_m2_contact_x = active_rect.cx()
                    else:
                        m1_m2_contact_x = fill_x + active_rect.lx() + 0.5 * contact.m1m2.height
                    self.add_contact_center(m1m2.layer_stack, offset=vector(m1_m2_contact_x, y_offset),
                                            size=[1, num_contacts], rotate=90)

                # connect vdd/gnd's using M2
                min_index = min(all_indices)
                max_index = max(all_indices)
                y_offset = self.get_contact_mid_y(min_index, is_nmos=is_nmos)
                y_top = self.get_contact_mid_y(max_index, is_nmos=is_nmos)
                self.add_rect(METAL2, offset=vector(m1_m2_contact_x - 0.5 * m1m2.height,
                                                    y_offset),
                              width=m1m2.height, height=y_top - y_offset)

            if fill_x is None:
                continue

            # Add m1, m2 fills at the power indices
            for j in all_indices:
                if is_nmos and j == 0:  # connected to gnd pin, no fill needed
                    continue
                elif is_pmos and j == num_fingers:  # connected to vdd pin, no fill needed
                    continue
                fill_y = self.get_contact_mid_y(j, is_nmos) - 0.5 * fill_height
                real_fill_x = fill_x + active_rect.lx()
                self.add_rect(METAL1, offset=vector(real_fill_x, fill_y),
                              width=fill_width, height=fill_height)

    def connect_outputs(self):
        nmos_indices = self.get_output_indices(is_nmos=True)
        pmos_indices = self.get_output_indices(is_nmos=False)

        indices = [nmos_indices, pmos_indices]

        connecting_rects = []

        for i in range(2):
            is_nmos = i == 0
            active_rect = self.nmos_active if is_nmos else self.pmos_active
            for index in indices[i]:
                x_offset = active_rect.lx() + 0.5 * active_rect.width
                y_offset = self.get_contact_mid_y(index, is_nmos) - 0.5 * self.m1_width
                rect = self.add_rect(METAL1, offset=vector(x_offset, y_offset),
                                     width=self.output_x - x_offset)
                connecting_rects.append(rect)
        bottom_out = min(connecting_rects, key=lambda x: x.by()).by()
        top_out = max(connecting_rects, key=lambda x: x.by()).uy()
        self.add_layout_pin("Z", METAL1, offset=vector(self.output_x, bottom_out),
                            height=top_out - bottom_out)

    def connect_power(self):

        destination_pins = ["gnd", "vdd"]

        for i in range(2):
            # connect to rail
            dummy_contact = contact.contact(contact.active.layer_stack, dimensions=[1, 1])

            pin = self.get_pin(destination_pins[i])
            is_nmos = i == 0
            active_rect = self.nmos_active if is_nmos else self.pmos_active
            index = 0 if is_nmos else self.num_fingers
            y_offset = self.get_contact_mid_y(index, is_nmos)
            x_offset = active_rect.lx() + 0.5 * active_rect.width - 0.5 * dummy_contact.height
            self.add_rect(METAL1, offset=vector(x_offset, y_offset), width=dummy_contact.height,
                          height=pin.cy() - y_offset)

    def add_poly_contact(self, contact_mid_x, poly_mid_y):
        poly_width = self.contact_width + 2 * contact.poly.first_layer_vertical_enclosure
        poly_height = self.contact_width + 2 * contact.poly.first_layer_horizontal_enclosure

        self.add_rect_center(CONTACT, offset=vector(contact_mid_x, poly_mid_y))
        self.add_rect_center(POLY, offset=vector(contact_mid_x, poly_mid_y),
                             width=poly_width, height=poly_height)

    def connect_inputs(self):

        nmos_poly_offsets, pmos_poly_offsets, _ = self.get_poly_y_offsets(self.num_fingers)
        nmos_poly_offsets = list(reversed(nmos_poly_offsets))

        if len(nmos_poly_offsets) == 3:
            pin_names = ["C", "B", "A"]
        else:
            pin_names = ["B", "A"]

        x_offset = self.gate_contact_x + 0.5 * self.contact_width - 0.5 * self.m1_width

        for i in range(len(pin_names)):
            pin_name = pin_names[i]

            nmos_y = nmos_poly_offsets[i] + 0.5 * self.poly_width
            pmos_y = pmos_poly_offsets[i] + 0.5 * self.poly_width
            contact_mid_x = self.gate_contact_x + 0.5 * self.contact_width

            for y_offset in [nmos_y, pmos_y]:
                self.add_poly_contact(contact_mid_x, y_offset)

            if i == 0:
                m1_ext = 0.5 * contact.poly.second_layer_height
                pin_width = self.nand_nor_pin_width
                x_offset = contact_mid_x - 0.5 * self.m1_width
            else:
                m1_ext = 0.5 * contact.poly.second_layer_width
                pin_width = self.m1_width

            pin_y = nmos_y - m1_ext

            pin = self.add_layout_pin(pin_name, METAL1, offset=vector(x_offset, pin_y),
                                      height=pmos_y - nmos_y + 2 * m1_ext,
                                      width=pin_width)

            if i > 0:
                self.add_rect(METAL1, offset=vector(x_offset, pin_y),
                              width=self.pin_right_x - x_offset,
                              height=contact.poly.second_layer_width)
                self.add_rect(METAL1, offset=vector(x_offset, pin.uy()
                                                    - contact.poly.second_layer_width),
                              width=self.pin_right_x - x_offset,
                              height=contact.poly.second_layer_width)

            x_offset -= (self.get_parallel_space(METAL1) + self.m1_width)

    def add_technology_specific_layers(self):
        if hasattr(tech, "add_tech_layers"):
            tech.add_tech_layers(self)

    def add_power_pins(self, layer=METAL1):
        pin_names = ["gnd", "vdd"]
        y_offsets = [-0.5 * self.rail_height, self.height - 0.5 * self.rail_height]
        for i in range(2):
            self.add_layout_pin(pin_names[i], layer, offset=vector(0, y_offsets[i]),
                                width=self.width, height=self.rail_height)

    def get_char_data_file_suffixes(self, **kwargs):
        return [("beta", parameter["beta"])]
