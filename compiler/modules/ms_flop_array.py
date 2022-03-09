import debug
from base import design
from base import utils
from base.library_import import library_import
from globals import OPTS
from modules.bitcell_aligned_array import BitcellAlignedArray


@library_import
class ms_flop_tap(design.design):
    """
    Nwell and Psub body taps for ms flop
    """
    pin_names = []
    lib_name = OPTS.ms_flop_tap_mod


class ms_flop_array(BitcellAlignedArray):
    """
    An Array of D-Flipflops used for to store Data_in & Data_out of
    Write_driver & Sense_amp, address inputs of column_mux &
    hierdecoder
    """

    def create_body_tap(self):
        if OPTS.use_x_body_taps:
            self.body_tap = ms_flop_tap()
            debug.info(1, "Using body tap {} for {}".format(self.body_tap.name,
                                                            self.name))

    body_tap_insts = []

    def __init__(self, columns, word_size, name="", align_bitcell=True, flop_mod=None,
                 flop_tap_name=None):
        self.columns = columns
        self.word_size = word_size
        if flop_mod is None:
            flop_mod = OPTS.ms_flop_mod
        if flop_tap_name is None:
            flop_tap_name = OPTS.ms_flop_tap_mod
        if name == "":
            name = "flop_array_c{0}_w{1}".format(columns, word_size)
            name += "_{}".format(flop_mod) if not flop_mod == OPTS.ms_flop_mod else ""
            name += "_{}".format(flop_tap_name) if not flop_tap_name == OPTS.ms_flop_tap_mod else ""

        self.flop_mod = flop_mod
        self.flop_tap_name = flop_tap_name
        self.align_bitcell = align_bitcell

        self.name = name
        super().__init__(columns=columns, word_size=word_size)

    def get_mod_name(self):
        return self.flop_mod

    @property
    def bus_pins(self):
        return ["din", "dout", "dout_bar"]

    def get_name(self):
        return self.name

    @property
    def mod_name(self):
        return self.flop_mod

    def get_bitcell_offsets(self):
        if self.align_bitcell:
            return super().get_bitcell_offsets()
        else:
            return [i * self.ms.width for i in range(self.columns)], [], []

    def create_modules(self):
        self.child_mod = self.ms = self.create_mod_from_str(OPTS.ms_flop, self.flop_mod)
        self.height = self.child_mod.height
        if OPTS.use_x_body_taps and self.flop_tap_name:
            self.body_tap = ms_flop_tap(self.flop_tap_name)
            self.add_mod(self.body_tap)

    def add_pins(self):
        for i in range(self.word_size):
            self.add_pin("din[{0}]".format(i))
        for i in range(self.word_size):
            self.add_pin("dout[{0}]".format(i))
            self.add_pin("dout_bar[{0}]".format(i))
        self.add_pin("clk")
        self.add_pin("vdd")
        self.add_pin("gnd")

    def analytical_delay(self, slew, load=0.0):
        return self.ms.analytical_delay(slew=slew, load=load)
