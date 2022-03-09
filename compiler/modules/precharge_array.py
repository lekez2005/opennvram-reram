import debug
from base import design
from base.design import NWELL, PWELL
from base.geometry import NO_MIRROR
from base.vector import vector
from globals import OPTS
from modules.precharge import precharge, precharge_tap


class precharge_array(design.design):
    """
    Dynamically generated precharge array of all bitlines.  Cols is number
    of bit line columns, height is the height of the bit-cell array.
    """

    def __init__(self, columns, size=1, name=None):
        name = name or "precharge_array"
        design.design.__init__(self, name)
        debug.info(1, "Creating {0} with precharge size {1:.3g}".format(self.name, size))

        self.columns = columns
        self.size = size
        self.create_modules()

        self.height = self.pc_cell.height

        self.add_pins()
        self.create_layout()
        self.DRC_LVS()

    def create_modules(self):
        if hasattr(OPTS, "precharge"):
            self.pc_cell = self.create_mod_from_str(OPTS.precharge, size=self.size)
        else:
            self.pc_cell = precharge(name="precharge", size=self.size)
            self.add_mod(self.pc_cell)
        self.child_mod = self.pc_cell

        if OPTS.use_x_body_taps:
            self.body_tap = precharge_tap(self.pc_cell)
            self.add_mod(self.body_tap)

    def add_pins(self):
        """Adds pins for spice file"""
        for i in range(self.columns):
            self.add_pin("bl[{0}]".format(i))
            self.add_pin("br[{0}]".format(i))
        self.add_pin("en")
        self.add_pin("vdd")

    def create_layout(self):
        self.add_insts()
        for vdd_pin in self.pc_cell.get_pins("vdd"):
            self.add_layout_pin(text="vdd", layer=vdd_pin.layer, offset=vdd_pin.ll(),
                                width=self.width, height=vdd_pin.height())
        en_pin = self.pc_cell.get_pin("en")
        self.add_layout_pin(text="en",
                            layer=en_pin.layer,
                            offset=en_pin.ll(),
                            width=self.width,
                            height=en_pin.height())

    def load_bitcell_offsets(self):
        bitcell_array_cls = self.import_mod_class_from_str(OPTS.bitcell_array)
        offsets = bitcell_array_cls.calculate_x_offsets(num_cols=self.columns)
        (self.bitcell_offsets, self.tap_offsets, _) = offsets

    def get_cell_offset(self, column):
        offset = vector(self.bitcell_offsets[column], 0)
        mirror = NO_MIRROR
        return offset, mirror

    def get_connections(self, col):
        return f"bl[{col}] br[{col}] en vdd".split()

    def add_insts(self):
        """Creates a precharge array by horizontally tiling the precharge cell"""
        self.load_bitcell_offsets()
        self.child_insts = []
        for i in range(self.columns):
            name = "mod_{0}".format(i)
            offset, mirror = self.get_cell_offset(i)
            inst = self.add_inst(name=name, mod=self.pc_cell, offset=offset,
                                 mirror=mirror)
            self.child_insts.append(inst)
            self.copy_layout_pin(inst, "bl", "bl[{0}]".format(i))
            self.copy_layout_pin(inst, "br", "br[{0}]".format(i))
            self.connect_inst(self.get_connections(i))
        if getattr(self, "body_tap", None):
            for x_offset in self.tap_offsets:
                self.add_inst(self.body_tap.name, self.body_tap, offset=vector(x_offset, 0))
                self.connect_inst([])
        self.width = inst.rx()
        self.extend_wells()

    def extend_wells(self):
        # fill wells
        layers = [NWELL]
        if self.has_pwell:
            layers.append(PWELL)
        for layer in layers:
            layer_shapes = self.pc_cell.get_layer_shapes(layer)
            if not layer_shapes:
                continue
            rect = layer_shapes[0]
            enclosure = self.well_enclose_ptx_active
            self.add_rect(layer, offset=vector(-enclosure, rect.by()),
                          width=self.width + 2 * enclosure, height=rect.height)
