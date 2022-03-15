import debug
from base import utils
from base.contact import well_contact, contact, active_contact, m1m2
from base.design import design, TAP_ACTIVE, ACTIVE, METAL2, NIMP, PIMP, PWELL, NWELL
from base.geometry import NO_MIRROR, MIRROR_Y_AXIS
from base.unique_meta import Unique
from base.vector import vector
from base.well_active_contacts import calculate_num_contacts
from tech import drc, add_tech_layers, spice as tech_spice, info as tech_info


class Diode(design, metaclass=Unique):
    @classmethod
    def get_name(cls, width, length, well_type=NWELL, m=1):
        name = f"{well_type}_diode_w_{width:.4g}_l_{length:.4g}".replace(".", "__")
        if m > 1:
            name += f"_m{m}"
        return name

    def __init__(self, width, length, well_type=NWELL, m=1):
        assert well_type in [NWELL, PWELL]
        name = self.get_name(width, length, well_type, m)
        debug.info(1, "Creating diode with name %s", name)
        self.diode_width = utils.ceil_2x_grid(width)
        self.diode_length = utils.ceil_2x_grid(length)
        self.well_type = well_type
        self.mults = m
        super().__init__(name=name)
        self.create_layout()
        self.add_pin_list(["p", "n"])
        add_tech_layers(self)

    def create_layout(self):
        if self.mults > 1:
            self.create_mult_diode()
            return
        self.calculate_dimensions()
        self.add_active()
        self.add_tap()
        self.add_diode_well()
        self.add_boundary()

    def create_mult_diode(self):
        finger = Diode(width=self.diode_width, length=self.diode_length, well_type=self.well_type,
                       m=1)
        self.add_mod(finger)
        self.finger = finger
        self.diode_insts = []
        self.diode_length = finger.diode_length
        self.diode_width = finger.diode_width

        for i in range(self.mults):
            if i % 2 == 0:
                mirror = NO_MIRROR
                if i == 0:
                    x_offset = 0
                else:
                    x_offset = self.diode_insts[-1].rx()
            else:
                mirror = MIRROR_Y_AXIS
                pin_name = self.well_type[0]
                previous_pin = self.diode_insts[-1].get_pin(pin_name)
                current_pin = finger.get_pin(pin_name)
                pin_mid = finger.width - current_pin.cx()
                x_offset = previous_pin.cx() - pin_mid + finger.width
            inst = self.add_inst(f"D_{i}", mod=finger, offset=vector(x_offset, 0), mirror=mirror)
            self.connect_inst(finger.pins)
            self.diode_insts.append(inst)
            self.copy_layout_pin(inst, "p")
            self.copy_layout_pin(inst, "n")
        self.height = finger.height
        self.width = self.diode_insts[-1].rx()

    def sp_write_file(self, sp, usedMODS):
        area = self.diode_width * self.diode_length
        perimeter = 2 * (self.diode_width + self.diode_length)
        if tech_spice["scale_tx_parameters"]:
            l_unit = "u"
            a_unit = "p"
        else:
            l_unit = ""
            a_unit = ""
        diode_name = tech_spice[f"{self.well_type[0]}_diode_name"]
        pin_str = " ".join(self.pins)
        spice_device = ""
        for i in range(self.mults):
            spice_device += f"D{i} {pin_str} {diode_name} pj={perimeter:.4g}{l_unit} " \
                           f"area={area:.4g}{a_unit}\n"
        sp.write(f"\n.SUBCKT {self.name} {pin_str}\n {spice_device}.ENDS\n")

    def calculate_dimensions(self):
        implant_enclosure = drc.get("implant_enclosure_diode")

        active_contact_active = active_contact.get_layer_shapes(ACTIVE)[0]
        self.diode_length = max(self.diode_length, active_contact_active.height)
        self.diode_width = max(self.diode_width, active_contact_active.width)
        self.implant_enclosure = implant_enclosure
        self.diode_implant_height = self.diode_length + 2 * implant_enclosure
        self.diode_implant_width = self.diode_width + 2 * implant_enclosure

        tap_contact = contact(layer_stack=well_contact.layer_stack, implant_type=self.well_type[0],
                              well_type=self.well_type)

        tap_active_width = tap_contact.get_layer_shapes(TAP_ACTIVE)[0].width

        self.tap_active_height = self.diode_implant_height - 2 * self.implant_enclose_active
        _, min_tap_active_width = self.calculate_min_area_fill(self.tap_active_height, layer=TAP_ACTIVE)
        self.tap_active_width = max(tap_active_width, min_tap_active_width, m1m2.w_2)
        self.tap_implant_width = max(self.tap_active_width + self.implant_enclose_active,
                                     self.implant_width)

        active_tap_space = drc.get("active_to_body_active")
        self.tap_space = max(0, active_tap_space - implant_enclosure)

        self.add_well = tech_info.get(f"has_{self.well_type}")
        if self.add_well:
            well_enclosure = self.well_enclose_active
            self.active_x_offset = max(self.implant_enclosure, well_enclosure)
            self.height = max(self.diode_implant_height,
                              max(self.diode_length, self.tap_active_height) + 2 * well_enclosure)
        else:
            self.active_x_offset = self.implant_enclosure
            self.height = self.diode_implant_height

        self.implant_x_offset = self.active_x_offset - self.implant_enclosure
        self.tap_implant_x_offset = (self.implant_x_offset + self.diode_implant_width +
                                     self.tap_space)
        self.width = (self.tap_implant_x_offset + self.implant_enclose_active +
                      self.tap_active_width + self.active_x_offset)
        self.mid_y = 0.5 * self.height

        debug.info(2, "%s, Width = %4.4g Height = %4.4g", self.name, self.width, self.height)

    def add_active(self):
        active_width = self.diode_width
        active_height = self.diode_length
        # active and diode layers
        offset = vector(self.active_x_offset, self.mid_y - 0.5 * active_height)
        self.add_rect(ACTIVE, offset, width=active_width, height=active_height)
        self.add_rect("diode", offset, width=active_width, height=active_height)

        offset = vector(self.active_x_offset + 0.5 * active_width, self.mid_y)
        # active to m2 vias
        via_insts = []
        for via in [active_contact, m1m2]:
            num_x_contacts = calculate_num_contacts(self, active_width,
                                                    layer_stack=via.layer_stack)
            num_y_contacts = calculate_num_contacts(self, active_height,
                                                    layer_stack=via.layer_stack)
            via_insts.append(self.add_contact_center(via.layer_stack, offset,
                                                     size=[num_x_contacts, num_y_contacts]))

        implant_type = NIMP if self.well_type.startswith("p") else PIMP
        # pins
        self.add_layout_pin_center_rect(implant_type[0], METAL2, offset=offset)
        # implant
        implant_offset = vector(self.implant_x_offset, self.mid_y - 0.5 * self.diode_implant_height)
        if implant_offset.x < 0.5 * self.implant_space:
            diode_implant_width = self.diode_implant_width + implant_offset.x
            implant_offset.x = 0
        else:
            diode_implant_width = self.diode_implant_width
        self.add_rect(implant_type, implant_offset, width=diode_implant_width,
                      height=self.diode_implant_height)

    def add_tap(self):
        # implant
        implant_type = PIMP if self.well_type.startswith("p") else NIMP
        implant_offset = vector(self.tap_implant_x_offset, self.mid_y - 0.5 * self.diode_implant_height)
        self.add_rect(implant_type, implant_offset, width=self.tap_implant_width,
                      height=self.diode_implant_height)
        # add body contact
        offset = vector(implant_offset.x + 0.5 * self.tap_implant_width, self.mid_y)
        via_insts = []
        for via in [well_contact, m1m2]:
            num_contacts = calculate_num_contacts(self, self.tap_active_height,
                                                  layer_stack=via.layer_stack)
            via_insts.append(self.add_contact_center(via.layer_stack, offset,
                                                     size=[1, num_contacts]))
        # add tap active
        tap_active = max(via_insts[0].get_layer_shapes(TAP_ACTIVE), key=lambda x: x.area)
        tap_offset = vector(tap_active.cx() - 0.5 * self.tap_active_width, tap_active.by())
        self.add_rect(TAP_ACTIVE, tap_offset, width=self.tap_active_width,
                      height=tap_active.height)
        # add pin
        m2_rect = max(via_insts[1].get_layer_shapes(METAL2), key=lambda x: x.area)
        self.add_layout_pin(implant_type[0], METAL2, offset=m2_rect.ll(), width=m2_rect.width,
                            height=m2_rect.height)

    def add_diode_well(self):
        if not self.add_well:
            return
        self.add_rect(self.well_type, vector(0, 0), width=self.width, height=self.height)
