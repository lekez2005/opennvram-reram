from base import design
from base.library_import import library_import
from globals import OPTS


@library_import
class tri_gate(design.design):
    """
    This module implements the tri gate cell used in the design for
    bit-line isolation. It is a hand-made cell, so the layout and
    netlist should be available in the technology library.  
    """

    lib_name = OPTS.tri_gate_mod
