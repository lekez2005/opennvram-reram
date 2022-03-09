from typing import TYPE_CHECKING

from base import contact
from base import utils
from base.contact_full_stack import ContactFullStack
from base.vector import vector

if TYPE_CHECKING:
    from sram import sram
else:
    class sram:
        pass


class Mixin(sram):

    def get_m1_vdd(self, bank_inst):
        return list(filter(lambda x: x.layer == "metal1", bank_inst.get_pins("vdd")))

    def get_m2_gnd(self, bank_inst):
        return list(filter(lambda x: x.layer == "metal2", bank_inst.get_pins("gnd")))

    def route_one_bank_power(self):
        m1mbottop = self.route_control_logic_power()

        # add vdd pin
        vdd_pin = next(filter(lambda x: not x.layer == "metal1", self.bank_inst.get_pins("vdd")))
        self.add_layout_pin("vdd", vdd_pin.layer, vdd_pin.ll(), vdd_pin.width(), vdd_pin.height())

        # add gnd pin
        gnd_pin = next(filter(lambda x: not x.layer == "metal1", self.bank_inst.get_pins("gnd")))
        self.add_layout_pin("gnd", gnd_pin.layer, gnd_pin.ll(), gnd_pin.width(), gnd_pin.height())

        # shift vias relative to banks
        gnd_rails = list(map(lambda x: utils.transform_relative(x.offset, self.bank_inst).y, self.bank.gnd_grid_rects))

        bottom_power_layer = self.bank.bottom_power_layer

        control_gnd = self.control_logic_inst.get_pin("gnd")
        rail_height = m1mbottop.second_layer_height

        for gnd_rail in gnd_rails:
            if control_gnd.by() + rail_height < gnd_rail < control_gnd.uy() - rail_height:
                self.add_rect(bottom_power_layer, offset=vector(gnd_pin.cx(), gnd_rail - m1mbottop.second_layer_height),
                              height=rail_height,
                              width=control_gnd.cx() - gnd_pin.cx())

    def filter_control_logic_vias(self):

        m1mbottop = ContactFullStack(start_layer=0, stop_layer=1, centralize=False, dimensions=[[1, 5]])  # e.g M1-M9
        power_via_space = 2 * self.m3_space + m1mbottop.second_layer_height

        bank_inst = self.bank_inst if self.num_banks == 1 else self.bank_inst[0]

        def control_logic_shift(x):
            return utils.transform_relative(vector(0, x), self.control_logic_inst).y

        rblk_bar_vdd = control_logic_shift(self.control_logic_inst.mod.rblk_bar.get_pin("vdd").cy())
        clk_bar_gnd = control_logic_shift(self.control_logic_inst.mod.clk_bar.get_pin("gnd").cy())


        # filter vdd vias
        vdd_grid_bottom = list(map(lambda x: x.offset, bank_inst.mod.vdd_grid_rects))
        vdd_via_pos = list(map(lambda x: utils.transform_relative(x, bank_inst).y, vdd_grid_bottom))  # initial list

        gnd_grid_bottom = list(map(lambda x: x.offset, bank_inst.mod.gnd_grid_rects))
        gnd_via_pos = list(map(lambda x: utils.transform_relative(x, bank_inst).y, gnd_grid_bottom))  # initial list

        if 'X' in bank_inst.mirror:
            vdd_via_pos = list(map(lambda x: x - m1mbottop.height, vdd_via_pos))
            gnd_via_pos = list(map(lambda x: x - m1mbottop.height, gnd_via_pos))

        temp_vdd_via_pos = []
        for via_pos in vdd_via_pos:
            if 'X' in self.control_logic_inst.mirror:
                if clk_bar_gnd + power_via_space < via_pos < rblk_bar_vdd - power_via_space:
                    temp_vdd_via_pos.append(via_pos)
            else:
                if rblk_bar_vdd + power_via_space < via_pos < clk_bar_gnd - power_via_space:
                    temp_vdd_via_pos.append(via_pos)

        vdd_via_pos = temp_vdd_via_pos

        # filter gnd vias


        control_pins = list(map(bank_inst.get_pin, self.control_logic_outputs + ["bank_sel"]))
        bottom_control_pin = min(control_pins, key=lambda x: x.by()).by()
        temp_gnd_via_pos = []
        for via_pos in gnd_via_pos:
            if self.control_logic_inst.by() + power_via_space < via_pos < bottom_control_pin - power_via_space:
                temp_gnd_via_pos.append(via_pos)
        gnd_via_pos = temp_gnd_via_pos

        return vdd_via_pos, gnd_via_pos, m1mbottop

    def route_control_logic_power(self):
        vdd_via_pos, gnd_via_pos, m1mbottop = self.filter_control_logic_vias()

        control_gnd = self.control_logic_inst.get_pin("gnd")

        for via_pos in gnd_via_pos:
            self.add_inst(m1mbottop.name, m1mbottop,
                          offset=(control_gnd.rx(), via_pos), mirror="MY")
            self.connect_inst([])

        # create horizontal m1 connections from bank vdd to control vdd
        control_vdd = self.control_logic_inst.get_pin("vdd")
        bank_inst = self.bank_inst if self.num_banks == 1 else self.bank_inst[0]
        right_vdd = max(self.get_m1_vdd(bank_inst), key=lambda x: x.rx())
        current_y = control_vdd.by()

        bank_to_ctrl_space = control_vdd.lx() - right_vdd.rx()
        parallel_space = utils.ceil(self.metal1_min_enclosed_area/bank_to_ctrl_space)

        while current_y + control_vdd.width() < control_vdd.uy():
            self.add_rect("metal1", offset=vector(right_vdd.rx(), current_y), width=control_vdd.lx() - right_vdd.rx(),
                          height=control_vdd.width())

            current_y += control_vdd.width() + parallel_space

        return m1mbottop


    def route_bank_supply_rails(self, m1mbottop):
        """ Create rails at bottom. Connect veritcal rails to top and bottom. """

        # add bottom metal1 gnd rail across both banks
        self.add_rect(layer="metal1",
                      offset=vector(0, self.power_rail_pitch),
                      height=self.power_rail_width,
                      width=self.width)
        # add bottom metal3 rail across both banks
        self.add_rect(layer="metal3",
                      offset=vector(0, 0),
                      height=self.power_rail_width,
                      width=self.width)

        left_bank = self.bank_inst[0]


        top_power_layer = left_bank.mod.top_power_layer
        # add vdd pin
        mid_vdd = max(self.get_m1_vdd(left_bank), key=lambda x: x.lx())
        self.add_layout_pin("vdd", layer=top_power_layer, offset=mid_vdd.ll(),
                            width=mid_vdd.width(), height=mid_vdd.height())


        # add gnd pin
        left_gnd = self.get_m2_gnd(left_bank)[0]
        self.add_layout_pin("gnd", layer=top_power_layer, offset=left_gnd.ll(),
                            width=left_gnd.width(), height=left_gnd.height())

        # route bank vertical rails to bottom
        for i in [0, 1]:
            vdd_pins = self.get_m1_vdd(self.bank_inst[i])
            for vdd_pin in vdd_pins:
                vdd_pos = vdd_pin.ul()
                # Route to bottom
                self.add_rect(layer="metal1",
                              offset=vector(vdd_pos.x, self.power_rail_pitch),
                              height=self.horz_control_bus_positions["vdd"].y - self.power_rail_pitch,
                              width=vdd_pin.width())

            gnd_pins = self.get_m2_gnd(self.bank_inst[i])
            for gnd_pin in gnd_pins:
                gnd_pos = gnd_pin.ul()
                # Route to bottom
                self.add_rect(layer="metal2",
                              offset=vector(gnd_pos.x, 0),
                              height=gnd_pin.uy(),  # route to the top bank
                              width=gnd_pin.width())
                # Add vias at top
                bottom_contact = self.add_contact_center(contact.m2m3.layer_stack,
                                        offset=vector(gnd_pin.cx(), gnd_pin.uy() - 0.5 * self.m2_width),
                                        size=[1, 2], rotate=90)

                self.add_contact_center(contact.m2m3.layer_stack,
                                        offset=vector(gnd_pin.cx(), self.horz_control_bus_positions["gnd"].y),
                                        size=[1, 3], rotate=90)

                self.add_rect("metal3", offset=vector(gnd_pin.lx(), bottom_contact.by()), width=gnd_pin.width(),
                              height=self.horz_control_bus_positions["gnd"].y - bottom_contact.by())

                # Add vias at bottom
                right_rail_pos = vector(gnd_pin.lr().x, 0)
                self.add_via(layers=("metal2", "via2", "metal3"),
                             offset=right_rail_pos,
                             rotate=90,
                             size=[2, 3])

        reference_banks = [self.bank_inst[0]]  # via pos are measured relative to these
        if self.num_banks == 4:
            reference_banks.append(self.bank_inst[2])

        # shift vias relative to banks
        grid_rects = [left_bank.mod.vdd_grid_rects, left_bank.mod.gnd_grid_rects]

        vdd_rails = []
        gnd_rails = []
        all_rails = [vdd_rails, gnd_rails]

        for j in [0, 1]:
            for i in range(len(reference_banks)):
                via_pos_y = list(map(lambda x: utils.transform_relative(x.offset, reference_banks[i]).y, grid_rects[j]))
                if i == 0:
                    via_pos_y = [x - m1mbottop.second_layer_height for x in via_pos_y]
                all_rails[j].extend(via_pos_y)

        # connect vdd across from left to right
        left_bank = self.bank_inst[0]
        right_bank = self.bank_inst[1]
        bottom_power_layer = left_bank.mod.bottom_power_layer

        left_vdd = min(self.get_m1_vdd(left_bank), key=lambda x: x.lx())
        right_vdd = max(self.get_m1_vdd(right_bank), key=lambda x: x.rx())
        rail_width = right_vdd.lx() - left_vdd.lx()


        for vdd_rail in vdd_rails:
            self.add_rect(bottom_power_layer, offset=vector(left_vdd.cx(), vdd_rail),
                          height=m1mbottop.second_layer_height,
                          width=rail_width)

        # connect gnd grid rails from left to right
        left_gnd = self.get_m2_gnd(left_bank)[0]
        right_gnd = self.get_m2_gnd(right_bank)[0]
        rail_width = right_gnd.lx() - left_gnd.lx()
        for gnd_rail in gnd_rails:
            self.add_rect(bottom_power_layer, offset=vector(left_gnd.cx(), gnd_rail),
                          height=m1mbottop.second_layer_height,
                          width=rail_width)

    def route_two_banks_power(self):
        """ Create rails at bottom. Connect veritcal rails to top and bottom. """

        m1mbottop = self.route_control_logic_power()

        self.route_bank_supply_rails(m1mbottop)

        left_bank = self.bank_inst[0]

        # connect the bank MSB flop supplies and control vdd
        vdd_pins = self.msb_address_inst.get_pins("vdd")
        bank1_vdd = max(self.get_m1_vdd(left_bank), key=lambda x: x.rx())
        for vdd_pin in vdd_pins:
            if vdd_pin.layer != "metal1": continue
            self.add_rect("metal1", height=vdd_pin.height(),
                          width=vdd_pin.lx() - bank1_vdd.rx(),
                          offset=vector(bank1_vdd.rx(), vdd_pin.by()))


        # connect msb ground to control_logic ground
        gnd_pins = self.msb_address_inst.get_pins("gnd")
        control_gnd = self.control_logic_inst.get_pin("gnd")

        # extend control ground to top msb ground
        top_msb_gnd = max(gnd_pins, key=lambda x: x.uy())
        self.add_rect("metal1", width=control_gnd.width(),
                                  height=top_msb_gnd.uy() - control_gnd.uy(),
                                  offset=control_gnd.ul())
        for gnd_pin in gnd_pins:
            if gnd_pin.layer != "metal1": continue
            self.add_rect("metal1", height=gnd_pin.height(),
                          width=control_gnd.lx() - gnd_pin.rx(),
                          offset=gnd_pin.lr())


    def connect_address_decoder_control_gnd(self):
        # connect msb_address, decoder and control_logic gnd pins
        gnd_pins = self.msb_address_inst.get_pins("gnd") + self.msb_decoder_inst.get_pins("gnd")
        gnd_pins = list(filter(lambda x: x.layer == "metal1", gnd_pins))
        right_most_pin = max(gnd_pins, key=lambda x: x.rx())
        bottom_gnd = min(gnd_pins, key=lambda x: x.by())
        top_gnd = max(gnd_pins, key=lambda x: x.by())
        x_extension = 2 * self.m1_space
        for gnd_pin in gnd_pins:
            self.add_rect("metal1", height=gnd_pin.height(),
                          width=right_most_pin.rx() - gnd_pin.rx() + x_extension,
                          offset=gnd_pin.lr())

        control_gnd = self.control_logic_inst.get_pin("gnd")

        x_offset = right_most_pin.rx() + x_extension
        self.add_rect("metal1", offset=vector(x_offset, control_gnd.uy()),
                      width=bottom_gnd.height(),
                      height=top_gnd.uy() - control_gnd.uy())
        self.add_rect("metal1", offset=vector(x_offset, control_gnd.uy()), height=bottom_gnd.height(),
                      width=control_gnd.rx() - x_offset)

    def route_four_banks_power(self):

        m1mbottop = self.route_control_logic_power()

        self.route_bank_supply_rails(m1mbottop)

        # connect msb_address, decoder and control_logic vdd pins
        vdd_pins = self.msb_address_inst.get_pins("vdd") + self.msb_decoder_inst.get_pins("vdd")
        bank1_vdd = max(self.get_m1_vdd(self.bank_inst[0]), key=lambda x: x.rx())
        for vdd_pin in vdd_pins:
            if vdd_pin.layer != "metal1": continue
            self.add_rect("metal1", height=vdd_pin.height(),
                          width=vdd_pin.lx() - bank1_vdd.rx(),
                          offset=vector(bank1_vdd.rx(), vdd_pin.by()))

        self.connect_address_decoder_control_gnd()


        top_vdd = max(self.bank_inst[2].get_pins("vdd"), key=lambda x: x.by())
        for i in [0, 1]:
            bank_inst = self.bank_inst[i]
            for pin in (bank_inst.get_pins("vdd") +
                        list(filter(lambda x: not x.layer == "metal2", bank_inst.get_pins("gnd")))):
                self.add_rect(pin.layer, offset=pin.ul(), width=pin.width(), height=top_vdd.by()-pin.uy())
            for pin in self.get_m2_gnd(bank_inst):
                self.add_rect("metal2", offset=vector(pin.lx(), self.horz_control_bus_positions["gnd"].y),
                              height=top_vdd.by() - self.horz_control_bus_positions["gnd"].y,
                              width=pin.width())
