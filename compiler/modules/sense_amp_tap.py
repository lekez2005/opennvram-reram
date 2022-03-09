from base import design
from base.library_import import library_import
from globals import OPTS


@library_import
class sense_amp_tap(design.design):
    lib_name = getattr(OPTS, "sense_amp_tap_mod",
                       getattr(OPTS, "sense_amp_tap"))
