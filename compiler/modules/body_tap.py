from base.design import design
from base.library_import import library_import
from globals import OPTS


@library_import
class body_tap(design):
    """
    A single bit cell (6T, 8T, etc.) body tap for bitcells without nwell/psub taps within the bitcell itself
    """

    pin_names = []
    lib_name = getattr(OPTS, "body_tap_mod", OPTS.body_tap)
