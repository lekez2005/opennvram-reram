from typing import TYPE_CHECKING

import caravel_config
from base.contact import m3m4, m2m3, contact, well_contact, m1m2
from base.design import METAL2, METAL4, design, NWELL, PWELL, METAL3
from base.flatten_layout import flatten_rects
from base.vector import vector
from base.well_active_contacts import calculate_num_contacts
from globals import OPTS
from tech import add_tech_layers

if TYPE_CHECKING:
    from .caravel_wrapper import CaravelWrapper
else:
    class CaravelWrapper:
        pass


class PadEsdDiode(design):
    def __init__(self):
        name = "caravel_esd_diode"
        super().__init__(name)
        self.create_layout()

    def create_layout(self):
        self.add_pin_list(["pad", "vdd", "gnd"])
        self.create_modules()
        self.add_modules()
        self.route_layout()
        add_tech_layers(self)
        self.add_boundary()

    def create_modules(self):
        self.diode = self.create_mod_from_str(OPTS.diode, well_type=NWELL,
                                              width=caravel_config.esd_diode_width,
                                              length=caravel_config.esd_diode_length,
                                              m=caravel_config.esd_diode_mults)
        self.add_mod(self.diode)

        num_contacts = calculate_num_contacts(self, self.diode.width - 2 * self.well_enclose_active,
                                              layer_stack=well_contact.layer_stack)

        self.pwell_contact = contact(layer_stack=well_contact.layer_stack, implant_type=PWELL[0],
                                     well_type=PWELL, dimensions=[1, num_contacts])

    def add_modules(self):
        self.height = self.diode.width
        y_offset = 0.5 * self.height - 0.5 * self.pwell_contact.height

        self.pwell_cont_inst = self.add_inst(self.pwell_contact.name,
                                             self.pwell_contact, vector(0, y_offset))
        self.connect_inst([])

        space = self.implant_space
        x_offset = self.pwell_cont_inst.rx() + space + self.diode.height

        self.left_inst = self.add_inst("left", self.diode, vector(x_offset, 0),
                                       rotate=90)
        self.connect_inst(["gnd", "pad"])

        well_space = self.get_space(NWELL, prefix="different")
        x_offset = self.left_inst.rx() + well_space + self.diode.height

        self.right_inst = self.add_inst("right", self.diode, offset=vector(x_offset, 0),
                                        rotate=90)
        self.connect_inst(["pad", "vdd"])

    def route_layout(self):
        self.route_gnd()
        self.route_vdd()
        self.route_pad()

    def join_m2_to_pins(self, output_pin, diode_pin_name, diode_inst):
        all_m2_rects = diode_inst.get_layer_shapes(METAL2, recursive=True)

        for pin in diode_inst.get_pins(diode_pin_name):
            largest_m2 = max([x for x in all_m2_rects if x.overlaps(pin)],
                             key=lambda x: x.width * x.height)
            x_offset = output_pin.lx() if output_pin.lx() < largest_m2.lx() else output_pin.rx()

            self.add_rect(METAL2, vector(x_offset, largest_m2.by()), height=largest_m2.height,
                          width=largest_m2.cx() - x_offset)

    def route_gnd(self):
        m1_cont = self.pwell_cont_inst
        num_contacts = calculate_num_contacts(self, m1_cont.height, layer_stack=m1m2.layer_stack)
        m2_cont = self.add_contact_center(m1m2.layer_stack, offset=vector(m1_cont.cx(), m1_cont.cy()),
                                          size=[1, num_contacts])
        m2_rect = max(m2_cont.get_layer_shapes(METAL2, recursive=True),
                      key=lambda x: x.width * x.height)
        m2_pin = self.add_layout_pin("gnd", METAL2, offset=m2_rect.ll(), width=m2_rect.width,
                                     height=m2_rect.height)

        self.join_m2_to_pins(m2_pin, "p", self.left_inst)

    def route_vdd(self):
        gnd_pin = self.get_pin("gnd")
        x_offset = self.right_inst.rx() + self.get_wide_space(METAL2)
        pin_width = m1m2.w_2

        m2_pin = self.add_layout_pin("vdd", METAL2, vector(x_offset, gnd_pin.by()),
                                     width=pin_width, height=gnd_pin.height())
        self.join_m2_to_pins(m2_pin, "n", self.right_inst)

        self.width = x_offset + pin_width

    def route_pad(self):
        gnd_pin = self.get_pin("gnd")
        pin_width = m1m2.w_2
        x_offset = 0.5 * (self.left_inst.rx() + self.right_inst.lx()) - 0.5 * pin_width

        m2_pin = self.add_layout_pin("pad", METAL2, vector(x_offset, gnd_pin.by()),
                                     width=pin_width, height=gnd_pin.height())
        self.join_m2_to_pins(m2_pin, "n", self.left_inst)
        self.join_m2_to_pins(m2_pin, "p", self.right_inst)


class CaravelEsdMixin(CaravelWrapper):

    def add_esd_diodes(self):
        self.add_diodes()
        self.route_diodes_to_pads()
        self.route_diodes_to_power()

    def create_diode(self):
        self.esd_diode = PadEsdDiode()
        self.add_mod(self.esd_diode)

    def add_diodes(self):
        from pin_assignments_mixin import num_analog, VDD_ESD, GND
        esd_space = caravel_config.esd_pad_to_diode

        pad_pin = self.esd_diode.get_pin("pad")

        self.diode_insts = {}

        for i in range(num_analog):
            pin_name = f"io_analog[{i}]"
            caravel_pin = self.wrapper_inst.get_pin(pin_name)
            if i in [4, 5, 6]:  # already clamped
                continue
            if self.is_top_pin(caravel_pin):
                x_offset = caravel_pin.cx() - pad_pin.cx()
                y_offset = caravel_pin.by() - esd_space - self.esd_diode.height
                rotate = 0
            else:
                if caravel_pin.rx() < 0.5 * 0.5 * self.wrapper_inst.width:
                    x_offset = caravel_pin.rx() + esd_space + self.esd_diode.height
                    y_offset = caravel_pin.cy() - pad_pin.cx()
                    rotate = 90
                else:
                    x_offset = caravel_pin.lx() - esd_space - self.esd_diode.height
                    rotate = 270
                    y_offset = caravel_pin.cy() - pad_pin.cx()  + self.esd_diode.width

            diode_inst = self.add_inst(f"esd_{pin_name}", self.esd_diode, vector(x_offset, y_offset),
                                       rotate=rotate)
            self.connect_inst([pin_name, VDD_ESD, GND])
            self.diode_insts[pin_name] = diode_inst

    @staticmethod
    def get_diode_pin(diode_inst, pin_name):
        m2_rects = diode_inst.get_layer_shapes(METAL2, recursive=True)
        n_pin = diode_inst.get_pin(pin_name)
        pin_overlaps = [x for x in m2_rects if x.overlaps(n_pin)]
        return max(pin_overlaps, key=lambda x: x.area)

    def route_diodes_to_pads(self):
        for pin_name, diode_inst in self.diode_insts.items():
            pad_pin = diode_inst.get_pin("pad")
            caravel_pin = self.wrapper_inst.get_pin(pin_name)
            is_top_pin = self.is_top_pin(caravel_pin)
            # connect to pad
            if is_top_pin:
                via_rotate = 0
                vias = [m2m3, m3m4]
            else:
                vias = [m2m3]
                via_rotate = 90

            for via in vias:
                self.add_contact_center(via.layer_stack, pad_pin.center(), rotate=via_rotate,
                                        size=[1, caravel_config.esd_num_contacts])

    def route_diodes_to_power(self):
        from router_mixin import m4m5
        from pin_assignments_mixin import VDD_ESD, GND
        num_contacts = caravel_config.esd_num_contacts

        sample_m3m4 = contact(m3m4.layer_stack, dimensions=[1, num_contacts])
        sample_m4m5 = contact(m4m5.layer_stack, dimensions=[1, num_contacts])

        destinations = {"vdd": VDD_ESD, "gnd": GND}

        for pin_name, diode_inst in self.diode_insts.items():
            caravel_pin = self.wrapper_inst.get_pin(pin_name)
            is_top_pin = self.is_top_pin(caravel_pin)

            for power_pin_name in ["vdd", "gnd"]:
                diode_pin = diode_inst.get_pin(power_pin_name)
                m3m4_via_offset = diode_pin.center()
                if is_top_pin:
                    self.add_contact_center(m2m3.layer_stack, diode_pin.center(), size=[1, num_contacts])
                    via_rotate = 0
                else:
                    self.add_contact_center(m2m3.layer_stack, diode_pin.center(), size=[1, num_contacts],
                                            rotate=90)
                    via_rotate = 90
                    if power_pin_name == "vdd":
                        x_offset = diode_pin.rx() + self.m4_space
                        y_offset = diode_pin.cy() - 0.5 * sample_m3m4.w_1
                        self.add_rect(METAL3, vector(diode_pin.cx(), y_offset),
                                      width=x_offset + sample_m3m4.h_1 - diode_pin.cx(),
                                      height=sample_m3m4.w_1)
                        m3m4_via_offset = vector(x_offset + 0.5 * sample_m3m4.h_1, diode_pin.cy())

                m3m4_cont = self.add_contact_center(m3m4.layer_stack, m3m4_via_offset,
                                                    size=[1, num_contacts],
                                                    rotate=via_rotate)
                m4_rect = max(m3m4_cont.get_layer_shapes(METAL4, recursive=True),
                              key=lambda x: x.width * x.height)

                power_pins = self.horz_power_grid[destinations[power_pin_name]]
                power_pins = [x for x in power_pins
                              if x.lx() <= m4_rect.cx() <= x.rx()]
                closest_power = min(power_pins,
                                    key=lambda x: abs(x.cy() - diode_pin.cy()))

                if closest_power.cy() > m4_rect.cy():
                    bottom = m4_rect.by()
                    top = closest_power.cy() + 0.5 * sample_m4m5.h_1
                else:
                    bottom = closest_power.cy() - 0.5 * sample_m4m5.h_1
                    top = m4_rect.uy()
                m4_width = m4m5.w_1
                self.add_rect(METAL4, vector(m4_rect.cx() - 0.5 * m4_width, bottom),
                              width=m4_width, height=top - bottom)
                via_offset = vector(m4_rect.cx(), closest_power.cy())
                self.add_contact_center(m4m5.layer_stack, via_offset, size=[1, num_contacts])

    def flatten_diodes(self):
        diode_insts = [(index, inst) for index, inst in enumerate(self.insts)
                       if inst.mod == self.esd_diode]
        insts = [x[1] for x in diode_insts]
        indices = [x[0] for x in diode_insts]
        flatten_rects(self, insts=insts, inst_indices=indices, skip_export_spice=True)
