import tech
from base.contact import m1m2, well as well_contact, m2m3
from base.design import METAL2, PWELL, NWELL, METAL3, ACTIVE
from base.layout_clearances import find_clearances, HORIZONTAL
from base.vector import vector
from base.well_active_contacts import calculate_num_contacts
from modules.bitcell_vertical_aligned import BitcellVerticalAligned
from modules.stacked_wordline_driver_array import stacked_wordline_driver_array


class reram_wordline_driver_array(stacked_wordline_driver_array):
    def __init__(self, rows, buffer_stages=None, name=None):
        name = name or "wordline_driver_array"
        super().__init__(name=name, rows=rows, buffer_stages=buffer_stages)

    def get_en_rail_y(self, en_rail):
        return en_rail.by() - m2m3.h_2 - self.m3_space

    def add_modules(self):
        super().add_modules()
        self.fill_tap_well()

    def fill_tap_well(self):
        body_tap = self.logic_buffer.logic_inst.mod.create_pgate_tap()
        x_shift = self.buffer_insts[0].lx()
        x_offset = - body_tap.get_layer_shapes(NWELL)[0].width + x_shift
        right_rect = max(self.buffer_insts[1].get_layer_shapes(NWELL, recursive=True),
                         key=lambda x: x.rx())
        nwell_width = right_rect.rx() - x_offset

        for y_offset, y_top in BitcellVerticalAligned.calculate_nwell_y_fills(self):
            self.add_rect(NWELL, vector(x_offset, y_offset), height=y_top - y_offset,
                          width=nwell_width)

    def create_power_pins(self):
        super().create_power_pins()
        # add well contacts
        for pin_name in ["vdd", "gnd"]:
            layout_pins = list(sorted(self.get_pins(pin_name), key=lambda x: x.by()))
            sample_pin = layout_pins[-1]  # use top pin to avoid bottom en rail
            open_spaces = find_clearances(self, layer=METAL2, direction=HORIZONTAL,
                                          region=(sample_pin.by(), sample_pin.uy()),
                                          recursive=False)
            # calculate m1m2 via locations
            vias = []
            for open_space in open_spaces:
                available_space = open_space[1] - open_space[0] - 2 * self.m2_space
                mid_x = 0.5 * (open_space[0] + open_space[1])
                for via in [m1m2, m2m3]:
                    sample_contact = calculate_num_contacts(self, available_space,
                                                            layer_stack=via.layer_stack,
                                                            return_sample=True)
                    if sample_contact.h_2 < available_space:
                        vias.append((mid_x, sample_contact))
            # calculate well contact locations
            first_buffer_inst = self.logic_buffer.buffer_mod.module_insts[0]
            x_shift = self.logic_buffer.buffer_inst.lx()
            x_shift += first_buffer_inst.cx()
            well_contact_offsets = [x.lx() + x_shift for x in self.buffer_insts[:2]]
            available_space = first_buffer_inst.width - self.get_space(ACTIVE)
            sample_well = calculate_num_contacts(self, available_space,
                                                 layer_stack=well_contact.layer_stack,
                                                 return_sample=True)

            for pin in self.get_pins(pin_name):
                # well contacts
                well_type = PWELL if pin_name == "gnd" else NWELL
                for x_offset in well_contact_offsets:
                    offset = vector(x_offset, pin.cy())
                    self.add_contact_center(well_contact.layer_stack, offset, rotate=90,
                                            size=sample_well.dimensions,
                                            implant_type=well_type[0],
                                            well_type=well_type)
                # m3 pins
                self.add_layout_pin(pin_name, METAL3, pin.ll(), width=pin.width(),
                                    height=pin.height())
                for mid_x, sample_via in vias:
                    self.add_contact_center(sample_via.layer_stack, vector(mid_x, pin.cy()),
                                            size=sample_via.dimensions, rotate=90)
        tech.add_tech_layers(self)
