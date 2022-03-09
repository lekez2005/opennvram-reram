from abc import ABC
from typing import List, Union, Tuple

import debug
from base import utils
from base.design import design, NWELL
from base.geometry import NO_MIRROR, MIRROR_Y_AXIS
from base.vector import vector
from base.well_implant_fills import get_default_fill_layers
from globals import OPTS


class BitcellAlignedArray(design, ABC):
    """
    Helper methods for arrays that are column aligned with the bitcell array
    """

    child_mod = None  # module, instance of design class
    body_tap = None  #
    child_insts = None
    tap_insts = None
    mirror = False  # mirror instances

    def __init__(self, columns=None, words_per_row=None, word_size=None, cols=None,
                 *_, **__):
        name = self.get_name()
        design.__init__(self, name)
        if cols is not None:
            columns = cols
        if words_per_row is not None and word_size is not None:
            columns = word_size * words_per_row
        if word_size is not None:
            words_per_row = int(columns / word_size)

        self.mirror = self.__class__.mirror or OPTS.mirror_bitcell_y_axis
        self.word_size = int(columns / words_per_row)
        self.words_per_row = words_per_row
        self.num_columns = columns

        debug.info(1, "Creating {0}, {1} columns, {2} words per row".
                   format(self.name, columns, words_per_row))

        self.create_modules()
        self.add_pins()
        self.create_array()
        self.add_body_taps()
        self.fill_implants_and_nwell()
        self.add_dummy_polys()
        self.add_layout_pins()
        self.add_boundary()

        self.DRC_LVS()

    def get_name(self):
        """Name for the array"""
        raise NotImplementedError

    @property
    def mod_name(self) -> str:
        """Name of the module that's imported from gds/spice library"""
        raise NotImplementedError

    @property
    def tap_name(self) -> Union[str, None]:
        """Name of body tap module from gds library if body taps are needed"""
        return None

    @property
    def child_name(self) -> str:
        """For name of instances in spice netlist"""
        return "mod_{}"

    @property
    def bus_pins(self) -> List[str]:
        """List of pins for which [{}] will be appended e.g. bl, br"""
        raise NotImplementedError

    def get_bitcell_offsets(self) -> Tuple[List[float], List[float], List[float]]:
        """x offsets of of instances and taps """
        bitcell_array_cls = self.import_mod_class_from_str(OPTS.bitcell_array)
        offsets = bitcell_array_cls.calculate_x_offsets(num_cols=self.num_columns)
        return offsets

    def get_horizontal_pins(self):
        """Pins that span from left to right"""
        for pin_name in self.child_mod.pins:
            if pin_name in self.bus_pins:
                continue
            for pin in self.child_mod.get_pins(pin_name):
                if pin.width() >= self.child_mod.width:
                    yield pin

    def create_modules(self):
        """Create child_mod and body tap"""
        self.create_child_mod()
        self.create_body_tap()

    def create_child_mod(self):
        self.child_mod = self.create_mod_from_str(self.mod_name)
        debug.info(1, "Using module {} for {}".format(self.child_mod.name,
                                                      self.name))
        self.height = self.child_mod.height

    def create_body_tap(self):
        if self.tap_name and OPTS.use_x_body_taps:
            self.body_tap = self.create_mod_from_str(self.tap_name)
            debug.info(1, "Using body tap {} for {}".format(self.body_tap.name,
                                                            self.name))

    def create_array(self):
        """Add child instances"""
        self.bitcell_offsets, self.tap_offsets, _ = self.get_bitcell_offsets()
        bitcell_width = self.create_mod_from_str(OPTS.bitcell).width

        max_words_per_row = int(utils.round_to_grid(self.child_mod.width) /
                                utils.round_to_grid(bitcell_width))
        assert self.words_per_row >= max_words_per_row,\
            f"Module {self.child_mod.name} width is {self.child_mod.width:.3g} but " \
            f"bitcell width is {bitcell_width:.3g} => Min words_per_row = {max_words_per_row}"

        self.child_insts = []
        for word in range(self.word_size):
            col = word * self.words_per_row
            name = self.child_name.format(word)
            offset = vector(self.bitcell_offsets[col], 0)
            if self.mirror and col % 2 == 0:
                offset.x += self.child_mod.width
                mirror = MIRROR_Y_AXIS
            else:
                mirror = NO_MIRROR
            self.child_insts.append(self.add_inst(name, self.child_mod, offset,
                                                  mirror=mirror))
            self.connect_inst(self.get_instance_connections(word))
        self.width = self.bitcell_offsets[-1] + self.child_mod.width

    def add_body_taps(self):
        """Add body taps"""
        self.tap_insts = []
        if self.body_tap is not None:
            for x_offset in self.tap_offsets:
                self.tap_insts.append(self.add_inst(self.body_tap.name, self.body_tap,
                                                    offset=vector(x_offset, 0)))
                self.connect_inst([])

    def get_instance_connections(self, bus_index: int) -> List[str]:
        """Gets instance connections by formatting bus pins based on 'bus_index'"""
        child_pins = self.child_mod.pins
        bus_pins = self.bus_pins

        connections = []
        for pin_name in child_pins:
            if pin_name in bus_pins:
                connections.append(pin_name + "[{}]".format(bus_index))
            else:
                connections.append(pin_name)
        return connections

    def add_pin_if_exist(self, pin_name):
        """Adds a pin if it exists, if pin_name is in bus_pins, then adds as a bus"""
        if pin_name in self.child_mod.pins:
            if pin_name in self.bus_pins:
                for bus_index in range(self.word_size):
                    self.add_pin(pin_name + "[{}]".format(bus_index))
            else:
                self.add_pin(pin_name)

    def add_pins(self):
        """Add schematic pins"""
        bus_pins = self.bus_pins
        for pin_name in bus_pins:
            if pin_name not in self.child_mod.pins:
                continue
            for bus_index in range(self.word_size):
                self.add_pin(pin_name + "[{}]".format(bus_index))
        for pin_name in self.child_mod.pins:
            if pin_name not in bus_pins:
                self.add_pin(pin_name)

    def add_layout_pins(self):
        """Add layout pins. Horizontal pins span entire array
         bus pin names are formatted by column"""
        schematic_pins = set(self.pins)  # to ensure all pins are exported
        for pin in self.get_horizontal_pins():
            self.add_layout_pin(pin.name, pin.layer,
                                offset=vector(pin.lx(), pin.by()),
                                width=(self.width - pin.lx() +
                                       (pin.rx() - self.child_mod.width)),
                                height=pin.height())
            schematic_pins.discard(pin.name)

        for pin_name in self.bus_pins:
            if pin_name not in self.child_mod.pins:
                continue
            for bus_index in range(len(self.child_insts)):
                inst = self.child_insts[bus_index]
                new_pin_name = pin_name + "[{}]".format(bus_index)
                self.copy_layout_pin(inst, pin_name, new_pin_name)
                schematic_pins.remove(new_pin_name)

        # copy from first instance if pin hasn't been added.
        # Error will be generated for bus pins and pin name mismatches
        for pin_name in schematic_pins:
            self.copy_layout_pin(self.child_insts[0], pin_name)

    def fill_implants_and_nwell(self):
        """Fill implants and wells between child instances and body taps"""
        layers, purposes = get_default_fill_layers()
        for i in range(len(layers)):
            self.fill_array_layer_columns(layers[i], purpose=purposes[i])
            self.fill_array_layer_body_taps(layers[i], purpose=purposes[i])

    def fill_array_layer_columns(self, layer, purpose):
        """Fill implants and wells between child instances"""
        rects = self.child_mod.get_layer_shapes(layer, purpose=purpose, recursive=True)

        for word in range(self.word_size):
            for j in range(1, self.words_per_row):
                col = j + word * self.words_per_row
                x_offset = self.bitcell_offsets[col]
                for rect in rects:
                    if rect.rx() >= self.child_mod.width and rect.lx() <= 0:
                        self.add_rect(layer,
                                      offset=vector(x_offset + rect.lx(), rect.by()),
                                      height=rect.height, width=rect.width)

    def fill_array_layer_body_taps(self, layer, purpose):
        """ Fill implants and wells between body taps"""

        if not (hasattr(self, "tap_offsets") and len(self.tap_offsets) > 0):
            return

        rects = self.child_mod.get_layer_shapes(layer, purpose=purpose, recursive=True)

        if self.body_tap is not None:
            tap_rects = self.body_tap.get_layer_shapes(layer, purpose)
        else:
            tap_rects = []
        if len(tap_rects) > 0:
            # prevent overlaps
            return
        tap_width = utils.get_body_tap_width()

        right_buffer_x_offsets = getattr(OPTS, "repeaters_array_space_offsets", [])

        tap_offsets = self.tap_offsets
        if layer == NWELL:
            if len(right_buffer_x_offsets) > 0:
                tap_offsets += right_buffer_x_offsets

        for rect in rects:
            # only right hand side  needs to be extended, must also start on the left
            if rect.rx() >= self.child_mod.width and rect.lx() <= 0:
                right_extension = rect.rx() - self.child_mod.width
                for tap_offset in tap_offsets:
                    self.add_rect(layer, offset=vector(tap_offset, rect.by()), height=rect.height,
                                  width=tap_width + right_extension)

    def add_dummy_polys(self):
        """Add dummy poly's at edges"""
        self.add_dummy_poly(self.child_mod, self.child_insts, self.words_per_row)

    def analytical_delay(self, slew, load=0.0):
        return self.child_mod.analytical_delay(slew=slew, load=load)
