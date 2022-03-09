import math
from typing import TYPE_CHECKING

import debug
from base.hierarchy_spice import INOUT, OUTPUT

if TYPE_CHECKING:
    from .caravel_wrapper import ReRamWrapper as Wrapper
else:
    class Wrapper:
        pass

control_pins = ["clk", "sense_trig", "web", "csb", "vref", "vclamp", "vclampp"]
CLK, SENSE_TRIG, WEB, CSB, VREF, VCLAMP, VCLAMPP = control_pins
control_pins = ["clk"]

VDD_A1 = VDD_WORDLINE = "vdda1"
VDD_A2 = VDD_WRITE = "vdda2"
VCC_D1 = VDD = "vccd1"  # 1.8 V
VCC_D2 = "vccd2"  # 1.8 V

VSS_A1 = "vssa1"
VSS_A2 = "vssa2"
VSS_D1 = GND = "vssd1"
VSS_D2 = "vssd2"

ANALOG = "io_analog"
GPIO_ANALOG = "gpio_analog"
GPIO = "io"
GPIO_IN = "io_in"
GPIO_OUT = "io_out"
OEB = "io_oeb"

num_analog = 11
num_analog_gpio = 18
num_digital_gpio = 9

total_pins = num_analog + num_analog_gpio + num_digital_gpio
assert total_pins == 38, "Sanity check"


def analog(index):
    assert index < num_analog
    return f"{ANALOG}[{index}]"


def analog_gpio(index):
    assert index < num_analog_gpio
    return f"{GPIO_ANALOG}[{index}]"


def gpio(index):
    assert index < num_digital_gpio
    return f"{GPIO}[{index}]"


def address_pin(index):
    assert index < PinAssignmentsMixin.num_address_pins
    return f"addr[{index}]"


def data_in_pin(index):
    assert index < PinAssignmentsMixin.word_size
    return f"data[{index}]"


def data_out_pin(index):
    assert index < PinAssignmentsMixin.word_size
    return f"data_out[{index}]"


def mask_in_pin(index):
    assert index < PinAssignmentsMixin.word_size
    return f"mask[{index}]"


class PinShortMod:
    spice_device = "V{} {} 0"


class PinShortInst:
    def __init__(self, name):
        self.name = name
        self.mod = PinShortMod()

    def gds_write_file(self, *args, **kwargs):
        pass


class PinAssignmentsMixin(Wrapper):
    word_size = None
    num_address_pins = None

    def create_netlist(self):
        pins = self.wrapper_inst.mod.pins
        self.add_pin_list(pins)
        debug.info(1, "Copying caravel pins to top level")
        for pin_name in self.pins:
            self.copy_layout_pin(self.wrapper_inst, pin_name)

        # sram connections
        sram_conns = [x for x in self.sram_inst.mod.pins]
        for sram_pin, caravel_pin in self.sram_to_wrapper_conns.items():
            sram_conns[sram_conns.index(sram_pin)] = caravel_pin

        conn_index = self.insts.index(self.sram_inst)
        self.conns[conn_index] = sram_conns

        # wrapper to vdd/gnd connections
        # TODO shorts for LVS
        for source_pin, dest_pin in self.wrapper_to_wrapper_conns.items():
            inst_name = source_pin.replace("[", "_").replace("]", "")
            self.insts.append(PinShortInst(inst_name))
            self.conns.append([source_pin, dest_pin])

    def sp_write_file(self, sp, usedMODS):
        sp.write(f'.include "{self.sram_inst.mod.spice_file_name}"\n')
        super().sp_write_file(sp, usedMODS)

    def assign(self, sram_pin, wrapper_pin):
        sram_pin = sram_pin.lower()
        assert sram_pin in self.sram.pins
        assert sram_pin not in self.sram_to_wrapper_conns
        assert wrapper_pin not in self.sram_to_wrapper_conns.values()

        if wrapper_pin.startswith(GPIO + "["):
            pin_type, _ = self.sram.get_pin_type(sram_pin)
            assert not pin_type == INOUT, "inout not permitted for gpio pin"
            bit = wrapper_pin.replace(GPIO, "")
            oeb_pin = OEB + bit
            if pin_type == OUTPUT:
                wrapper_pin = GPIO_OUT + bit
                oeb_val = GND
            else:
                oeb_val = VDD
                wrapper_pin = GPIO_IN + bit
            self.assign_wrapper_power(oeb_pin, oeb_val)
            debug.info(2, f"{oeb_pin:<15s} <==> {oeb_val}")
        debug.info(2, f"{sram_pin:<15s} <==> {wrapper_pin}")
        self.sram_to_wrapper_conns[sram_pin] = wrapper_pin

    def assign_wrapper_power(self, source_pin, dest_pin):
        debug.info(3, f"{source_pin:<15s} <==> {dest_pin}")
        self.wrapper_to_wrapper_conns[source_pin] = dest_pin

    def assign_analog_pins(self):
        # assign analog pins to controls
        self.assign(CLK, analog(7))
        self.assign(SENSE_TRIG, analog(8))
        self.assign(WEB, analog(9))
        self.assign(CSB, analog(10))

        self.assign(VCLAMP, analog(0))
        self.assign(VCLAMPP, analog(1))
        self.assign(VREF, analog(2))
        # other analog pins
        self.assign(data_in_pin(0), analog(3))
        self.assign(data_out_pin(0), analog(4))
        self.assign(mask_in_pin(0), analog(5))
        # io_analog[6] not assigned

        for i in range(2):
            # TODO: pre-tapeout - clarify clamp voltages
            self.assign_wrapper_power(f"io_clamp_low[{i}]", GND)
            self.assign_wrapper_power(f"io_clamp_high[{i}]", VDD)

    @staticmethod
    def assign_gpio_pins(assignment_func):

        # 2 pins for data_others and mask_others
        # TODO: pre-tapeout - use mask bits in tri state driver to enable reading from all bits
        #  assignment_func("data_out_others", gpio(1))
        assignment_func("data_others", analog_gpio(0))
        assignment_func("mask_others", analog_gpio(1))

        available_gpio = num_digital_gpio
        available_analog_gpio = num_analog_gpio - 2

        analog_gpio_index = 2
        gpio_index = 0

        # all address pins are assigned
        for i in range(PinAssignmentsMixin.num_address_pins):
            if i < num_analog_gpio:
                assignment_func(address_pin(i), analog_gpio(analog_gpio_index))
                analog_gpio_index += 1
                available_analog_gpio -= 1
            else:
                assignment_func(address_pin(i), gpio(gpio_index))
                gpio_index += 1
                available_gpio -= 1

        assert available_gpio >= 0, "Insufficient pins to assign address pins"

        total_available = available_gpio + available_analog_gpio
        debug.info(2, "Number of pins for data/mask = %d", total_available)
        # data_in, mask_in, data_out
        num_data = math.floor(total_available / 3)
        debug.info(2, "Number of data bits to be connected = %d", 1 + num_data)

        def make_assignment(source_pin):
            nonlocal analog_gpio_index, gpio_index
            if analog_gpio_index < num_analog_gpio:
                assignment_func(source_pin, analog_gpio(analog_gpio_index))
                analog_gpio_index += 1
            else:
                assignment_func(source_pin, gpio(gpio_index))
                gpio_index += 1

        for bit in range(1, num_data + 1):
            make_assignment(data_in_pin(bit))
            make_assignment(mask_in_pin(bit))
            make_assignment(data_out_pin(bit))

        return num_data

    def assign_pins(self):
        # power
        self.assign("gnd", GND)
        self.assign("vdd", VDD)
        self.assign("vdd_write", VDD_WRITE)
        self.assign("vdd_wordline", VDD_WORDLINE)

        self.assign_analog_pins()

        def assign_func(sram_pin, wrapper_pin):
            self.assign(sram_pin, wrapper_pin)

        self.assign_gpio_pins(assign_func)

        unassigned = set(self.sram.pins) - set(self.sram_to_wrapper_conns.keys())
        if unassigned:
            debug.warning("Unassigned pins: %s", unassigned)
        assert not unassigned