from base import design
from base.library_import import library_import
from globals import OPTS


@library_import
class write_driver_tap(design.design):
    """
    Nwell and Psub body taps for write_driver
    """
    lib_name = getattr(OPTS, "write_driver_tap_mod",
                       getattr(OPTS, "write_driver_tap"))
