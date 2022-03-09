import debug
from base import design
from base import utils
from base.unique_meta import Unique
from tech import GDS, layer


def library_import(cls):
    """
    Class annotation to import gds and sp files from  tech library by specifying cls.lib_name and cls.pin_names
    The order of cls.pin_names should match that in the sp file
    Instantiations of the class should use cls.pin_names for pin assignment
    :param cls:
    :return:
    """
    class GdsLibImport(cls, metaclass=Unique):

        @classmethod
        def get_name(cls, mod_name=None):
            if mod_name is None:
                mod_name = cls.lib_name
            return mod_name

        def __init__(self, mod_name=None):
            mod_name = self.get_name(mod_name)
            design.design.__init__(self, mod_name)
            debug.info(2, "Create {}".format(mod_name))

            (self.width, self.height) = utils.get_libcell_size(mod_name, GDS["unit"], layer["boundary"])
            pin_names = getattr(self.__class__, "pin_names", self.pins)
            self.pin_map = utils.get_libcell_pins(pin_names, mod_name, GDS["unit"], layer["boundary"])

    return GdsLibImport
