from typing import TYPE_CHECKING

import debug
from base.design import METAL2
from base.vector import vector
from globals import OPTS

if TYPE_CHECKING:
    from modules.baseline_bank import BaselineBank
else:
    class BaselineBank:
        pass


class TwoPrechargeMixin(BaselineBank):
    """Banks with two precharge drivers"""

    @staticmethod
    def get_mixin_module_list():
        return ["br_precharge_array"]

    def update_vertical_stack(self, stack):
        stack.insert(stack.index(self.precharge_array_inst),
                     self.br_precharge_array_inst)
        return stack

    def create_precharge_array(self):
        self.precharge_array = self.create_module('precharge_array', columns=self.num_cols,
                                                  size=OPTS.precharge_size)
        self.create_br_precharge_array()

    def create_br_precharge_array(self):
        self.br_precharge_array = self.create_module('br_precharge_array',
                                                     columns=self.num_cols,
                                                     bank=self)

    def add_precharge_array(self):
        from modules.baseline_bank import EXACT
        y_offset = self.get_br_precharge_y()
        self.br_precharge_array_inst = self.add_inst(name="br_precharge_array",
                                                     mod=self.br_precharge_array,
                                                     offset=vector(0, y_offset))
        temp = []
        for i in range(self.num_cols):
            temp.append("bl[{0}]".format(i))
            temp.append("br[{0}]".format(i))
        temp.extend(self.br_precharge_array.pc_cell.pins[2:])
        replacements = [("en", "precharge_en_bar", EXACT)]
        temp = self.connections_from_mod(temp, replacements)
        self.connect_inst(temp)

        super().add_precharge_array()

    def get_precharge_y(self):
        y_space = self.calculate_bitcell_aligned_spacing(self.precharge_array,
                                                         self.br_precharge_array,
                                                         num_rails=0)
        return self.br_precharge_array_inst.uy() + y_space

    def get_br_precharge_y(self):
        from modules.baseline_bank import BaselineBank
        return BaselineBank.get_precharge_y(self)

    def route_precharge(self):
        self.route_all_instance_power(self.precharge_array_inst)
        self.route_all_instance_power(self.br_precharge_array_inst)

        self.route_precharge_to_bitcell()
        precharge_inst = self.precharge_array_inst
        self.precharge_array_inst = self.br_precharge_array_inst
        self.route_precharge_to_sense_or_mux()
        self.precharge_array_inst = precharge_inst

        self.join_bitlines(top_instance=self.precharge_array_inst, top_suffix="",
                           bottom_instance=self.br_precharge_array_inst,
                           bottom_suffix="", word_size=self.num_cols)


class WordlineVoltageMixin(BaselineBank):
    def get_mid_gnd_offset(self):
        """x offset for middle gnd rail"""
        offset = - self.wide_power_space - self.vdd_rail_width - self.bus_pitch
        debug.info(2, "Mid gnd offset = %.3g", offset)
        return offset

    def update_wordline_offset(self, offset):
        # leave space for wordline vdd
        offset -= ((self.wide_power_space + self.vdd_rail_width), 0.0)
        debug.info(2, "Wordline offset = %.3g", offset.x)
        return offset

    def update_wordline_driver_connections(self, connections):
        return self.connections_from_mod(connections, [("vdd", "vdd_wordline")])

    def get_wordline_vdd_offset(self):
        return self.mid_vdd.lx() - self.wide_power_space - self.vdd_rail_width

    def route_wordline_power_pins(self, wordline_driver_inst):
        # gnd
        for pin in wordline_driver_inst.get_pins("gnd"):
            self.add_rect(pin.layer, pin.lr(), height=pin.height(),
                          width=self.mid_gnd.rx() - pin.rx())
            self.add_power_via(pin, self.mid_gnd, 90)

        # vdd
        vdd_pins = list(sorted(wordline_driver_inst.get_pins("vdd"),
                               key=lambda x: x.by()))
        x_offset = self.get_wordline_vdd_offset()
        y_offset = vdd_pins[0].by()
        self.vdd_wordline = self.add_layout_pin("vdd_wordline", METAL2,
                                                vector(x_offset, y_offset),
                                                width=self.vdd_rail_width,
                                                height=vdd_pins[-1].uy() - y_offset)

        for pin in vdd_pins:
            self.add_rect(pin.layer, pin.lr(), height=pin.height(),
                          width=self.vdd_wordline.rx() - pin.rx())
            self.add_power_via(pin, self.vdd_wordline, 90)
