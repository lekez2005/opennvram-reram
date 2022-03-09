from base.design import design
from base.library_import import library_import
from globals import OPTS


@library_import
class write_driver_mask(design):
    """
    write driver
    """
    pin_names = "data data_bar mask_bar en en_bar bl br vdd gnd".split()
    lib_name = OPTS.write_driver_mod
