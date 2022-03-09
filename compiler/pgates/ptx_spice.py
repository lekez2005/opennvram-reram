import debug
from base import design
from base.vector import vector
from tech import drc
from . import ptx


class ptx_spice(ptx.ptx):
    """
    Module for representing spice transistor. No layout is drawn but module can still be instantiated for use in LVS
    """

    def __init__(self, width=drc["minwidth_tx"], mults=1, tx_type="nmos",
                 contact_pwell=True, contact_nwell=True, tx_length=None):
        name = "{0}_m{1}_w{2:.4g}".format(tx_type, mults, width)
        if not contact_pwell:
            name += "_no_p"
        if not contact_nwell:
            name += "_no_n"
        if tx_length is not None:
            name += "_l_{:.5g}".format(tx_length)
        else:
            tx_length = drc["minwidth_poly"]
        name = name.replace(".", "_")
        design.design.__init__(self, name)
        debug.info(3, "create ptx_spice structure {0}".format(name))

        self.tx_type = tx_type
        self.mults = mults
        self.tx_width = width
        self.tx_length = tx_length

        self.create_spice()
        self.width = self.height = 0

    def gds_write_file(self, newLayout):
        self.visited = True
        return
