import re

import debug
from base import design, utils
from base.contact import contact, m1m2, poly as poly_contact, active as active_contact, cross_poly
from base.design import METAL1, METAL2, POLY, ACTIVE, CONTACT, NWELL
from base.hierarchy_spice import INOUT, INPUT
from base.vector import vector
from base.well_active_contacts import calculate_num_contacts
from base.well_implant_fills import calculate_tx_metal_fill
from characterizer.characterization_data import load_data
from globals import OPTS
from tech import drc, info, spice, parameter, add_tech_layers
from tech import layer as tech_layers


class ptx(design.design):
    """
    This module generates gds and spice of a parametrically NMOS or
    PMOS sized transistor.  Pins are accessed as D, G, S, B.  Width is
    the transistor width. Mults is the number of transistors of the
    given width. Total width is therefore mults*width.  Options allow
    you to connect the fingered gates and active for parallel devices.

    """

    def __init__(self, width=drc["minwidth_tx"], mults=1, tx_type="nmos",
                 connect_active=False, connect_poly=False, num_contacts=None, dummy_pos=None,
                 active_cont_pos=None,
                 independent_poly=False,
                 contact_poly=False):
        # We need to keep unique names because outputting to GDSII
        # will use the last record with a given name. I.e., you will
        # over-write a design in GDS if one has and the other doesn't
        # have poly connected, for example.
        width = utils.ceil(width)
        name = "{0}_m{1}_w{2:.4g}".format(tx_type, mults, width)
        if connect_active:
            name += "_a"
        if connect_poly:
            name += "_p"
        if contact_poly:
            name += "_pc"
        if not connect_poly and independent_poly and mults > 1:
            # poly pitch will be calculated based on
            # min space between independent poly contacts
            name += "_pi"
        if active_cont_pos is not None:
            name += f"_ac_{''.join(map(str, active_cont_pos))}"
        if num_contacts:
            name += "_c{}".format(num_contacts)
        if dummy_pos is not None:
            name += "_d{}".format("".join([str(pos) for pos in dummy_pos]))
        # replace periods with underscore for newer spice compatibility
        name = re.sub('\.', '_', name)

        if dummy_pos is None:
            dummy_pos = list(range(0, 2 * self.num_poly_dummies))

        design.design.__init__(self, name)
        debug.info(3, "create ptx2 structure {0}".format(name))

        self.tx_type = tx_type
        self.mults = int(mults)
        self.tx_width = width
        self.tx_length = drc["minwidth_poly"]
        self.connect_active = connect_active
        self.connect_poly = connect_poly
        self.contact_poly = contact_poly
        self.num_contacts = num_contacts
        self.dummy_pos = dummy_pos
        self.independent_poly = independent_poly
        self.active_cont_pos = active_cont_pos

        self.create_spice()
        self.create_layout()
        add_tech_layers(self)

        rects = self.get_layer_shapes(METAL1) + self.get_layer_shapes(POLY)
        min_y = min(rects, key=lambda x: x.by()).by()
        self.height = max(rects, key=lambda x: x.uy()).uy() - min_y
        self.width = self.active_rect.width
        self.translate_all(vector(self.active_offset.x, min_y))
        self.add_boundary()

        # for run-time, we won't check every transitor DRC independently
        # but this may be uncommented for debug purposes
        # self.DRC()

    def setup_drc_constants(self):
        design.design.setup_drc_constants(self)

    @staticmethod
    def calculate_poly_pitch(obj: design.design, num_independent_contacts):
        poly_space = obj.poly_space
        if num_independent_contacts == 1:
            poly_width = obj.poly_width
        else:
            poly_width = poly_contact.first_layer_width
        pitch = poly_width + poly_space
        pitch = max(pitch, obj.contact_width + 2 * obj.contact_to_gate + obj.poly_width)
        return pitch - obj.poly_width, obj.poly_width, pitch

    @staticmethod
    def calculate_active_to_poly_cont_mid(tx_type, tx_width=None, use_m1m2=False):
        """Distance from edge of active to middle of poly contact"""
        # calculate based on contact
        active_to_poly_contact = drc.get(f"poly_contact_to_{tx_type[0]}_active",
                                         drc["poly_contact_to_active"])
        cont_space = active_to_poly_contact + 0.5 * poly_contact.contact_width
        if tx_width is not None:
            # calculate based on m1 space
            active_cont = calculate_num_contacts(None, tx_width, return_sample=True,
                                                 layer_stack=active_contact)
            n_metal_height = active_cont.h_2
            line_end_space = ptx.get_line_end_space(METAL1)
            poly_m1_height = poly_contact.h_2

            if use_m1m2:
                m1m2_cont = calculate_num_contacts(None, tx_width, return_sample=True,
                                                   layer_stack=m1m2)
                n_metal_height = max(n_metal_height, m1m2_cont.h_1)
                line_end_space = max(line_end_space, ptx.get_line_end_space(METAL2))
                poly_m1_height = max(poly_m1_height, m1m2.h_1)
            metal_extension = utils.round_to_grid(0.5 * n_metal_height - 0.5 * tx_width)

            m1_space = metal_extension + line_end_space + 0.5 * poly_m1_height
            return max(cont_space, m1_space)
        return cont_space

    def create_layout(self):
        """Calls all functions related to the generation of the layout"""
        self.setup_layout_constants()
        self.add_active()
        self.add_well_implant()
        self.add_poly()
        self.add_active_contacts()

    def create_spice(self):
        self.add_pin_list(["D", "G", "S", "B"], [INOUT, INPUT, INOUT, INPUT])

        # self.spice.append("\n.SUBCKT {0} {1}".format(self.name,
        #                                              " ".join(self.pins)))
        # Just make a guess since these will actually be decided in the layout later.
        area_sd = 2.5 * drc["minwidth_poly"] * self.tx_width
        perimeter_sd = 2 * drc["minwidth_poly"] + 2 * self.tx_width
        tx_length = self.tx_length
        width = self.tx_width * self.mults
        l_unit = "u"
        a_unit = "p"

        if not spice["scale_tx_parameters"]:
            l_unit = ""
            a_unit = ""

        tx_instance_prefix = spice.get("tx_instance_prefix", "M")
        self.spice_device = f"{tx_instance_prefix}{{0}} {{1}} {spice[self.tx_type]} m=1 " \
                            f"nf={int(self.mults)} w={width}{l_unit} " \
                            f"l={tx_length}{l_unit} pd={perimeter_sd}{l_unit}" \
                            f" ps={perimeter_sd}{l_unit} as={area_sd}{a_unit} ad={area_sd}{a_unit}"
        self.spice.append("\n* ptx " + self.spice_device)
        # self.spice.append(".ENDS {0}".format(self.name))

    def get_input_pins(self):
        return ["G"]

    @staticmethod
    def calculate_end_to_poly():
        # The enclosure of an active contact. Not sure about second term.
        active_width = design.design.get_min_layer_width(ACTIVE)
        contact_width = design.design.get_min_layer_width(CONTACT)
        active_enclose_contact = max(drc["active_enclosure_contact"],
                                     (active_width - contact_width) / 2)
        # This is the distance from the edge of poly to the contacted end of active
        return active_enclose_contact + contact_width + drc.get("contact_to_gate")

    def setup_layout_constants(self):
        """
        Pre-compute some handy layout parameters.
        """

        if self.num_contacts == None:
            self.num_contacts = self.calculate_num_contacts(self.tx_width)

        # Determine layer types needed
        if self.tx_type == "nmos":
            self.implant_type = "n"
            self.well_type = "p"
        elif self.tx_type == "pmos":
            self.implant_type = "p"
            self.well_type = "n"
        else:
            debug.error("Invalid transitor type.", -1)

        # This is not actually instantiated but used for calculations
        self.active_contact = contact(layer_stack=("active", "contact", "metal1"),
                                      dimensions=(1, self.num_contacts))
        if self.independent_poly and self.mults > 1:
            num_independent_contacts = self.mults
        else:
            num_independent_contacts = 1
        pitch_res = self.calculate_poly_pitch(self, num_independent_contacts)
        self.ptx_poly_space, _, self.poly_pitch = pitch_res

        self.end_to_poly = self.calculate_end_to_poly()

        # Active width is determined by enclosure on both ends and contacted pitch,
        # at least one poly and n-1 poly pitches
        self.active_width = 2 * self.end_to_poly + self.poly_width + (self.mults - 1) * self.poly_pitch

        # Active height is just the transistor width
        self.active_height = self.tx_width

        # The active offset is due to the well extension
        self.active_offset = vector([self.well_enclose_ptx_active] * 2)

        # Poly height must include poly extension over active
        self.poly_offset_y = self.active_offset.y + 0.5 * self.active_height
        # additional poly from adding poly_to_m1 via
        self.additional_poly = 0.0
        self.poly_height = self.tx_width + 2 * self.poly_extend_active
        if self.contact_poly:
            res = self.calculate_active_to_poly_cont_mid(self.tx_type, self.tx_width)
            self.active_to_contact_center = res
            poly_height = (self.poly_extend_active + self.tx_width +
                           self.active_to_contact_center +
                           0.5 * poly_contact.first_layer_height)
            self.additional_poly = poly_height - self.poly_height
            self.poly_height = poly_height
            if self.tx_type == "nmos":
                self.poly_offset_y += 0.5 * self.additional_poly
                self.poly_contact_center = (self.well_enclose_ptx_active + self.active_height +
                                            self.active_to_contact_center)
            else:
                self.poly_offset_y -= 0.5 * self.additional_poly
                self.poly_contact_center = self.well_enclose_ptx_active - self.active_to_contact_center

        self.poly_top = self.poly_offset_y + 0.5 * self.poly_height
        self.poly_bottom = self.poly_offset_y - 0.5 * self.poly_height

        # poly dummys
        if "po_dummy" in tech_layers:
            dummy_height = drc["po_dummy_min_height"]
            # top aligns with actual poly so poly_extend_active
            # bottom is po_dummy_enc
            alternative_dummy_height = (self.poly_height - self.poly_extend_active +
                                        drc["po_dummy_enc"])

            self.dummy_height = max(self.poly_height, alternative_dummy_height, dummy_height)
            # align top with real poly top
            if self.tx_type == "nmos":
                self.dummy_y_offset = self.poly_top - 0.5 * self.dummy_height
            else:
                self.dummy_y_offset = self.poly_offset_y
            self.dummy_top = self.dummy_y_offset + 0.5 * self.dummy_height
            self.dummy_bottom = self.dummy_y_offset - 0.5 * self.dummy_height
        else:
            self.dummy_top = self.poly_top
            self.dummy_bottom = self.poly_bottom

        # Well enclosure of active, ensure minwidth as well
        if self.implant_enclose_ptx_active > 0:

            implant_bottom = self.active_offset.y - self.implant_enclose_ptx_active
            implant_top = self.active_offset.y + self.active_height + self.implant_enclose_ptx_active

            poly_top = max(self.poly_top, self.dummy_top)
            poly_bottom = min(self.poly_bottom, self.dummy_bottom)

            implant_enclose_poly = 0
            if self.poly_vert_space:
                implant_enclose_poly = 0.5 * self.poly_vert_space
            if self.implant_enclose_poly:
                implant_enclose_poly = max(implant_enclose_poly, self.implant_enclose_poly)
                implant_top = max(implant_top, poly_top + implant_enclose_poly)
                implant_bottom = min(implant_bottom, poly_bottom - implant_enclose_poly)

            self.implant_top = implant_top
            self.implant_bottom = implant_bottom

            self.implant_height = self.implant_top - self.implant_bottom
            self.implant_offset = vector(self.active_offset.x + 0.5 * self.active_width,
                                         0.5 * (self.implant_top + self.implant_bottom))
        else:
            self.implant_height = max(self.active_height, drc.get("minwidth_implant"))
            self.implant_offset = (self.active_offset +
                                   vector(self.active_width, self.active_height).scale(0.5, 0.5))
        self.implant_width = self.active_width + 2 * self.implant_enclose_ptx_active

        if info["has_{}well".format(self.well_type)]:
            self.height = self.implant_height
            self.cell_well_width = max(self.active_width + 2 * self.well_enclose_ptx_active,
                                       self.well_width)
            self.width = self.cell_well_width
            self.cell_well_height = max(self.tx_width + 2 * self.well_enclose_ptx_active,
                                        self.well_width)
        else:
            # If no well, use the boundary of the active and poly
            self.height = self.poly_height
            self.width = self.active_width

        # Min area results are just flagged for now.
        debug.check(self.active_width * self.active_height >= drc["minarea_active"], "Minimum active area violated.")
        # We do not want to increase the poly dimensions to fix an area problem as it would cause an LVS issue.
        debug.check(self.poly_width * self.poly_height >= drc["minarea_poly"], "Minimum poly area violated.")

    def connect_fingered_poly(self, poly_positions):
        """
        Connect together the poly gates and create the single gate pin.
        The poly positions are the center of the poly gates
        and we will add a single horizontal connection.
        """
        # Nothing to do if there's one poly gate
        if len(poly_positions) < 2:
            return

        # Remove the old pin and add the new one
        self.remove_layout_pin("G")  # only keep the main pin

        # The width of the poly is from the left-most to right-most poly gate
        poly_width = poly_positions[-1].x - poly_positions[0].x + self.poly_width

        if self.contact_poly:
            self.add_layout_pin(text="G",
                                layer="metal1",
                                offset=vector(poly_positions[0].x, self.poly_contact_center) - [
                                    0.5 * self.m1_width] * 2,
                                width=poly_width,
                                height=self.m1_width)
        else:
            if self.tx_type == "pmos":
                # This can be limited by poly to active spacing or the poly extension
                distance_below_active = self.poly_width + max(self.poly_to_active, 0.5 * self.poly_height)
                poly_offset = poly_positions[0] - vector(0.5 * self.poly_width, distance_below_active)
            else:
                # This can be limited by poly to active spacing or the poly extension
                distance_above_active = max(self.poly_to_active, 0.5 * self.poly_height)
                poly_offset = poly_positions[0] + vector(-0.5 * self.poly_width, distance_above_active)

            self.add_layout_pin(text="G",
                                layer="poly",
                                offset=poly_offset,
                                width=poly_width,
                                height=drc["minwidth_poly"])

    def connect_fingered_active(self, drain_positions, source_positions):
        """
        Connect each contact  up/down to a source or drain pin
        """
        if self.mults == 1:
            return

        # This is the distance that we must route up or down from the center
        # of the contacts to avoid DRC violations to the other contacts
        pin_offset = vector(0, 0.5 * self.active_contact.second_layer_height \
                            + self.line_end_space + 0.5 * self.m1_width)
        # This is the width of a m1 extend the ends of the pin
        end_offset = vector(self.m1_width / 2, 0)

        # drains always go to the MIDDLE of the cell, so top of NMOS, bottom of PMOS
        # so reverse the directions for NMOS compared to PMOS.
        if self.tx_type == "pmos":
            drain_dir = -1
            source_dir = 1
        else:
            drain_dir = 1
            source_dir = -1
        source_offset = pin_offset.scale(source_dir, source_dir)
        self.remove_layout_pin("D")  # remove the individual connections
        if self.contact_poly:
            metal1_area_fill = None

            fill = calculate_tx_metal_fill(self.tx_width, self)
            if fill:
                y_offset, fill_top, fill_width, fill_height = fill
                # fill calculation assumes fill goes from up to down
                if drain_dir == 1:  # reverse for nmos
                    y_adjustment = (0.5 * self.tx_width - y_offset) + 0.5 * self.tx_width
                    fill_y = self.active_rect.by() + y_adjustment - fill_height
                else:
                    fill_y = self.active_rect.by() + y_offset

            for a in drain_positions:
                self.add_contact_center(layers=m1m2.layer_stack, offset=a)
                if fill:
                    fill_x = a.x - 0.5 * fill_width
                    metal1_area_fill = self.add_rect(layer=METAL1,
                                                     offset=vector(fill_x, fill_y),
                                                     width=fill_width, height=fill_height)
            if len(drain_positions) > 1:  # add m1m2 vias connect
                drain_pin_width = drain_positions[-1][0] - drain_positions[0][0] + self.m2_width
                self.add_layout_pin(text="D",
                                    layer=METAL2,
                                    offset=drain_positions[0] - vector(0.5 * self.m2_width,
                                                                       0.5 * m1m2.second_layer_height),
                                    width=drain_pin_width,
                                    height=m1m2.second_layer_height)
            else:
                # metal2 contact fill for drc
                metal2_fill_width, metal2_fill_height = self.calculate_min_area_fill(layer=METAL2)
                metal2_fill_width = max(metal2_fill_width, self.m2_width)
                metal2_fill_height = max(metal2_fill_height, self.m2_width)
                self.add_layout_pin_center_rect(text="D", layer=METAL2, offset=drain_positions[0],
                                                width=metal2_fill_width, height=metal2_fill_height)
            # source connection needs to be shifted when drain metal1 height is increased
            if metal1_area_fill is not None:
                distance_from_mid_contact = max(abs(metal1_area_fill.by() - drain_positions[0].y),
                                                abs(metal1_area_fill.uy() - drain_positions[0].y))
                source_offset = vector(pin_offset.x, distance_from_mid_contact + self.line_end_space
                                       + 0.5 * self.m1_width).scale(source_dir, source_dir)

        else:
            drain_offset = pin_offset.scale(drain_dir, drain_dir)
            # Add each vertical segment
            for a in drain_positions:
                self.add_path(METAL1, [a, a + drain_offset])
            # Add a single horizontal pin
            self.add_layout_pin_center_segment(text="D", layer=METAL1,
                                               start=drain_positions[0] + drain_offset - end_offset,
                                               end=drain_positions[-1] + drain_offset + end_offset)

        if len(source_positions) > 1:
            self.remove_layout_pin("S")  # remove the individual connections
            # Add each vertical segment
            for a in source_positions:
                self.add_path(METAL1, [a, a + source_offset])
            # Add a single horizontal pin
            self.add_layout_pin_center_segment(text="S", layer=METAL1,
                                               start=source_positions[0] + source_offset - end_offset,
                                               end=source_positions[-1] + source_offset + end_offset)

    def add_poly(self):
        """
        Add the poly gates(s) and (optionally) connect them.
        """
        # poly is one contacted spacing from the end and down an extension
        poly_offset = vector(self.active_offset.x + 0.5 * self.poly_width + self.end_to_poly, self.poly_offset_y)

        # poly_positions are the bottom center of the poly gates
        self.poly_positions = poly_positions = []

        # It is important that these are from left to right, so that the pins are in the right
        # order for the accessors
        for i in range(0, self.mults):
            # Add this duplicate rectangle in case we remove the pin when joining fingers
            self.add_rect_center(layer=POLY,
                                 offset=poly_offset,
                                 height=self.poly_height,
                                 width=self.poly_width)
            if self.contact_poly:
                contact_pos = vector(poly_offset.x, self.poly_contact_center)
                self.add_contact_center(layers=contact.poly_layers, offset=contact_pos,
                                        size=(1, 1))
                self.add_layout_pin_center_rect(text="G",
                                                layer=METAL1,
                                                offset=contact_pos,
                                                height=poly_contact.second_layer_height,
                                                width=poly_contact.second_layer_width)
            else:
                self.add_layout_pin_center_rect(text="G",
                                                layer="poly",
                                                offset=poly_offset,
                                                height=self.poly_height,
                                                width=self.poly_width)
            poly_positions.append(poly_offset)
            poly_offset = poly_offset + vector(self.poly_pitch, 0)

        # poly dummys
        if "po_dummy" in tech_layers:
            shifts = ([-self.mults - (i + 1) for i in reversed(range(self.num_poly_dummies))] +
                      list(range(self.num_poly_dummies)))
            for i in self.dummy_pos:
                self.add_rect_center(layer="po_dummy",
                                     offset=vector(poly_offset.x + self.poly_pitch * shifts[i], self.dummy_y_offset),
                                     height=self.dummy_height,
                                     width=self.poly_width)

        if self.connect_poly:
            self.connect_fingered_poly(poly_positions)

    def rotate_poly_contacts(self):
        """Use cross_poly for poly contacts.
        Removes existing poly contacts and layout pins and replaces them with
         cross_poly which has horizontal M1 """
        self.rename(self.name + "_cross")
        self.pin_map["g"] = []
        cont_indices = []
        for i, inst in enumerate(self.insts):
            if inst.mod.name == poly_contact.name:
                cont_indices.append(i)
                offset = vector(inst.cx(), inst.cy())
                self.add_cross_contact_center(cross_poly, offset)
                self.add_layout_pin_center_rect("G", METAL1, offset)

        self.insts = [x for i, x in enumerate(self.insts) if i not in cont_indices]
        self.conns = [x for i, x in enumerate(self.conns) if i not in cont_indices]

    def add_active(self):
        """ 
        Adding the diffusion (active region = diffusion region) 
        """
        self.active_rect = self.add_rect(layer="active",
                                         offset=self.active_offset,
                                         width=self.active_width,
                                         height=self.active_height)

    def add_well_implant(self):
        """
        Add an (optional) well and implant for the type of transistor.
        """
        if info["has_{}well".format(self.well_type)]:
            self.add_rect(layer="{}well".format(self.well_type),
                          offset=(0, 0),
                          width=self.cell_well_width,
                          height=self.cell_well_height)
        # If the implant must enclose the active, shift offset
        # and increase width/height
        self.implant_rect = self.add_rect_center(layer="{}implant".format(self.implant_type),
                                                 offset=self.implant_offset,
                                                 width=self.implant_width,
                                                 height=self.implant_height)

    def get_contact_positions(self):
        """
        Create a list of the centers of drain and source contact positions.
        """
        mid_y = self.active_rect.cy()
        poly_mid_to_cont_mid = (0.5 * self.poly_width + self.contact_to_gate
                                + 0.5 * active_contact.contact_width)
        # The first one will always be a source
        # This is the center of the first active contact offset (centered vertically)
        poly_x_start = self.poly_positions[0].x

        contact_positions = [vector(poly_x_start - poly_mid_to_cont_mid, mid_y)]
        # It is important that these are from left to right, so that the pins are in the right
        # order for the accessors.
        for i in range(self.mults - 1):
            contact_positions.append(vector(self.poly_positions[i].x +
                                            0.5 * self.poly_pitch, mid_y))

        contact_positions.append(vector(self.poly_positions[-1].x + poly_mid_to_cont_mid,
                                        mid_y))
        return contact_positions

    def add_active_contacts(self):
        """
        Add the active contacts to the transistor.
        """

        contact_positions = self.get_contact_positions()
        self.contact_positions = contact_positions
        if self.active_cont_pos is not None:
            contact_positions = [contact_positions[x] for x in self.active_cont_pos]

        source_positions = contact_positions[::2]
        drain_positions = contact_positions[1::2]

        for pos in source_positions:
            contact = self.add_contact_center(layers=("active", "contact", "metal1"),
                                              offset=pos,
                                              size=(1, self.num_contacts),
                                              implant_type=None,
                                              well_type=None)
            self.add_layout_pin_center_rect(text="S",
                                            layer="metal1",
                                            offset=pos,
                                            width=contact.mod.second_layer_width,
                                            height=contact.mod.second_layer_height)

        for pos in drain_positions:
            contact = self.add_contact_center(layers=("active", "contact", "metal1"),
                                              offset=pos,
                                              size=(1, self.num_contacts),
                                              implant_type=None,
                                              well_type=None)
            self.add_layout_pin_center_rect(text="D",
                                            layer="metal1",
                                            offset=pos,
                                            width=contact.mod.second_layer_width,
                                            height=contact.mod.second_layer_height)

        if self.connect_active:
            self.connect_fingered_active(drain_positions, source_positions)

    @staticmethod
    def get_mos_active(parent_mod: design.design, tx_type="n"):
        all_active = parent_mod.get_layer_shapes(ACTIVE, recursive=True)
        all_poly = parent_mod.get_layer_shapes(POLY, recursive=True)
        all_nwell = parent_mod.get_layer_shapes(NWELL, recursive=True)

        def is_overlap(reference, rects):
            return any(reference.overlaps(x) for x in rects)

        mos_active = [x for x in all_active if is_overlap(x, all_poly)]
        mos_active = [x for x in mos_active if x.width > parent_mod.poly_pitch]
        if tx_type[0] == "n":
            return [x for x in mos_active if not is_overlap(x, all_nwell)]
        else:
            return [x for x in mos_active if is_overlap(x, all_nwell)]

    @staticmethod
    def flatten_tx_inst(parent_mod: design.design, tx_inst):
        """Move all rects from transistor instance to parent_mod"""
        from base.flatten_layout import flatten_rects
        inst_index = parent_mod.insts.index(tx_inst)
        flatten_rects(parent_mod, [tx_inst], [inst_index])

    def is_delay_primitive(self):
        """Whether to descend into this module to evaluate sub-modules for delay"""
        return True

    def get_input_cap(self, pin_name, num_elements: int = 1, wire_length: float = 0.0,
                      interpolate=True, **kwargs):
        # ignore interpolate
        cap_val = self.get_tx_cap(tx_type=self.tx_type[0], terminal=pin_name,
                                  width=self.tx_width, nf=self.mults,
                                  m=1, interpolate=True)
        return cap_val * num_elements, cap_val

    @staticmethod
    def get_tx_cap(tx_type, terminal="g", width=None, nf: int = 1, m: int = 1,
                   interpolate=True):
        """
        Load transistor parasitic caps
        :param tx_type: "p" or "n"
        :param terminal: "d" or "g"
        :param width: in um -> This is width per finger, total width will be width*nf
        :param nf: number of fingers
        :param m: number of transistors
        :param interpolate: Interpolate between fingers if exact nf not characterized
        :return: capacitance in F
        """
        terminal = terminal.lower()
        terminal = "d" if terminal == "s" else terminal
        unit_cap = None
        if width is None:
            width = spice["minwidth_tx"]
        if OPTS.use_characterization_data:
            cell_name = tx_type + "mos"
            file_suffixes = [("beta", parameter["beta"])]
            size = width / spice["minwidth_tx"]
            size_suffixes = [("nf", nf)]
            unit_cap = load_data(cell_name=cell_name, pin_name=terminal, size=size,
                                 file_suffixes=file_suffixes, size_suffixes=size_suffixes,
                                 interpolate_size_suffixes=interpolate)
        if unit_cap is None:
            if terminal == "d":
                unit_cap = spice["min_tx_drain_c"] / spice["minwidth_tx"] * 1e-15
            elif terminal == "g":
                unit_cap = spice["min_tx_gate_c"] / spice["minwidth_tx"] * 1e-15
            else:
                debug.error("Invalid tx terminal {}".format(terminal), -1)
        debug.info(4, "Unit cap for terminal {} width {} nf {} = {:.4g}".format(
            terminal, width, nf, unit_cap))
        return unit_cap * width * nf * m

    def get_driver_resistance(self, pin_name, use_max_res=False, interpolate=None, corner=None):
        return self.get_tx_res(tx_type=self.tx_type[0], width=self.tx_width, nf=self.mults,
                               m=1, interpolate=interpolate)

    @staticmethod
    def get_tx_res(tx_type, width=None, nf: int = 1, m: int = 1, interpolate=True, corner=None):
        """Load resistance for tx. Same parameters as get_tx_cap, Corner is (process, vdd, temperature)"""
        res_per_micron = None
        if width is None:
            width = spice["minwidth_tx"]
        if not spice["scale_tx_parameters"]:
            width /= 1e6
        if OPTS.use_characterization_data:
            cell_name = tx_type + "mos"
            if corner is not None:
                file_suffixes = [("process", corner[0]), ("vdd", corner[1]), ("temp", corner[2])]
            else:
                file_suffixes = []
            size_suffixes = [("nf", nf)]
            size = width / spice["minwidth_tx"]
            res_per_micron = load_data(cell_name=cell_name, pin_name="resistance", size=size,
                                       file_suffixes=file_suffixes, size_suffixes=size_suffixes,
                                       interpolate_size_suffixes=interpolate)

        if res_per_micron is None:
            key = "min_tx_r_" + tx_type
            res_per_micron = spice[key] * spice["minwidth_tx"]
        return res_per_micron / width / nf / m
