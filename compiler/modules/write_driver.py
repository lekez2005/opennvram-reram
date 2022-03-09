from base.design import design
from base.library_import import library_import
from base.vector import vector
from globals import OPTS


@library_import
class write_driver(design):
    """
    Tristate write driver to be active during write operations only.       
    This module implements the write driver cell used in the design. It
    is a hand-made cell, so the layout and netlist should be available in
    the technology library.
    """

    lib_name = OPTS.write_driver_mod


class write_driver_modify_bitlines(design):
    def __init__(self):
        self.child_mod = write_driver()
        self.name = f"{self.child_mod.name}_mod"
        design.__init__(self, self.name)
        self.add_mod(self.child_mod)
        self.create_layout()
        self.add_boundary()

    def create_layout(self):
        self.child_inst = self.add_inst("child_mod", self.child_mod, vector(0, 0))
        self.connect_inst(self.child_mod.pins)

        self.width = self.child_mod.width
        self.height = self.child_mod.height

        bitcell = self.create_mod_from_str(OPTS.bitcell)
        for pin_name in ["bl", "br"]:
            bitcell_pin = bitcell.get_pin(pin_name)
            child_pin = self.child_inst.get_pin(pin_name)

            offset = vector(bitcell_pin.lx(), child_pin.uy() - bitcell_pin.width())
            self.add_rect(child_pin.layer, offset, width=child_pin.cx() - offset.x)
            self.add_layout_pin(pin_name, child_pin.layer, offset,
                                width=bitcell_pin.width(),
                                height=self.height - offset.y)

        for pin in self.child_mod.pins:
            self.add_pin(pin)
            if pin not in self.pin_map:
                self.copy_layout_pin(self.child_inst, pin)
