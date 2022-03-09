from base import design
from base.library_import import library_import
from globals import OPTS


@library_import
class latched_sense_amp_tap(design.design):
    """
    Contains two bitline logic cells stacked vertically
    """
    pin_names = []
    lib_name = getattr(OPTS, "sense_amp_tap_mod", "latched_sense_amp_tap")
