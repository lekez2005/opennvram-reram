from importlib import reload

from modules import body_tap
from base import contact
from base import design
from base import utils
from base.vector import vector
from globals import OPTS
from pgates.pinv import pinv
from pgates.ptx import ptx
from tech import drc
from tech import layer as tech_layers


class replica_bitline(design.design):
    """
    Generate a module that simulates the delay of control logic 
    and bit line charging. Stages is the depth of the delay
    line and rows is the height of the replica bit loads.
    """

    def __init__(self, delay_stages, delay_fanout, bitcell_loads, name="replica_bitline"):
        design.design.__init__(self, name)

        g = reload(__import__(OPTS.delay_chain))
        self.mod_delay_chain = getattr(g, OPTS.delay_chain)

        g = reload(__import__(OPTS.replica_bitcell))
        self.mod_replica_bitcell = getattr(g, OPTS.replica_bitcell)

        c = __import__(OPTS.bitcell)
        self.mod_bitcell = getattr(c, OPTS.bitcell)

        c = __import__(OPTS.bitcell_array)
        self.mod_bitcell_array = getattr(c, OPTS.bitcell_array)

        for pin in ["en", "out", "vdd", "gnd"]:
            self.add_pin(pin)
        self.bitcell_loads = bitcell_loads
        self.delay_stages = delay_stages
        self.delay_fanout = delay_fanout

        self.rail_offset = 0.5*drc["implant_to_implant"]

        self.create_modules()
        self.calculate_module_offsets()
        self.add_modules()
        self.route()
        self.calculate_dimensions()
        self.add_lvs_correspondence_points()

        self.DRC_LVS()

    def calculate_dimensions(self):
        top_gnd = sorted(self.dc_inst.get_pins("gnd"), key=lambda x: x.uy())[-1]
        self.height = max(top_gnd.uy(), self.rbl_inst.uy())
        self.width = self.right_vdd.rx()

    def calculate_module_offsets(self):
        """ Calculate all the module offsets """
        
        # These aren't for instantiating, but we use them to get the dimensions
        self.poly_contact_offset = vector(0.5*contact.poly.width,0.5*contact.poly.height)

        # M1/M2 routing pitch is based on contacted pitch
        self.m1_pitch = self.m1_width + self.m1_space

        # leave space below the cells for pins and bitcell overshoots
        fill_width = self.m1_width
        self.fill_height = utils.ceil(drc["minarea_metal1_contact"] / fill_width)
        self.bottom_y_offset = self.fill_height + self.line_end_space + 0.5*self.inv.rail_height

        self.en_rail_offset = 0

        self.left_vdd_offset = vector(self.en_rail_offset+0.5*self.m2_width, 0)

        self.nwell_extension = self.inv.mid_y + self.inv.nwell_height - self.inv.height

        self.inverter_delay_chain_space = 2*self.nwell_extension + self.get_parallel_space("nwell")

        self.rbl_inv_offset = vector(self.left_vdd_offset.x + self.rail_height + self.parallel_line_space,
                                     self.bottom_y_offset)

        tx_x_offset = self.rbl_inv_offset.x + 0.5 * (self.access_tx.width - self.access_tx.active_width)

        tx_y_offset = self.rbl_inv_offset.y + self.inv.height + (- self.access_tx.implant_rect.offset.y +
                                                                 0.5*self.inv.well_contact_implant_height)

        self.access_tx_offset = vector(tx_x_offset, tx_y_offset)

        self.delay_chain_offset = vector(self.rbl_inv_offset.x,
                                         self.rbl_inv_offset.y + self.inv.height + self.access_tx.height +
                                         self.inverter_delay_chain_space)


        gnd_space = self.line_end_space
        self.gnd_offset = vector(2*self.m1_space + max(self.rbl_inv_offset.x + self.inv.width,
                                                 self.delay_chain_offset.x + self.delay_chain.width), 0)
        self.wl_x_offset = self.gnd_offset.x + self.rail_height + gnd_space

        rbl_x_offset = self.wl_x_offset + self.m1_width + self.line_end_space - self.replica_bitcell.get_pin("vdd").lx()

        self.bitcell_offset = vector(rbl_x_offset + self.rbl.bitcell_offsets[0], self.bottom_y_offset)
        self.rbl_offset = vector(rbl_x_offset, self.bitcell_offset.y + self.replica_bitcell.height)

        self.delayed_rail_x = self.gnd_offset.x - self.parallel_line_space - self.m1_width



    def create_modules(self):
        """ Create modules for later instantiation """
        self.replica_bitcell = self.mod_replica_bitcell()
        self.add_mod(self.replica_bitcell)

        # This is the replica bitline load column that is the height of our array
        self.rbl = self.mod_bitcell_array(name="bitline_load", cols=1, rows=self.bitcell_loads)
        self.add_mod(self.rbl)

        # FIXME: The FO and depth of this should be tuned
        self.delay_chain = self.mod_delay_chain([self.delay_fanout]*self.delay_stages, cells_per_row=2)
        self.add_mod(self.delay_chain)

        self.inv = pinv()
        self.add_mod(self.inv)

        self.access_tx = ptx(tx_type="pmos")
        self.add_mod(self.access_tx)

    def add_modules(self):
        """ Add all of the module instances in the logical netlist """
        # This is the threshold detect inverter on the output of the RBL
        self.rbl_inv_inst=self.add_inst(name="rbl_inv",
                                        mod=self.inv,
                                        offset=self.rbl_inv_offset + vector(self.inv.width, 0),
                                        mirror="MY",
                                        rotate=0)
        self.connect_inst(["bl[0]", "out", "vdd", "gnd"])

        self.tx_inst=self.add_inst(name="rbl_access_tx",
                                   mod=self.access_tx,
                                   offset=self.access_tx_offset,
                                   rotate=0)
        # D, G, S, B
        self.connect_inst(["vdd", "delayed_en", "bl[0]", "vdd"])
        # add the well and poly contact

        self.dc_inst=self.add_inst(name="delay_chain",
                                   mod=self.delay_chain,
                                   offset=self.delay_chain_offset,
                                   rotate=0)
        self.connect_inst(["en", "delayed_en", "vdd", "gnd"])

        self.rbc_inst=self.add_inst(name="bitcell",
                                    mod=self.replica_bitcell,
                                    offset=self.bitcell_offset)
        self.connect_inst(["bl[0]", "br[0]", "delayed_en", "vdd", "gnd"])

        self.rbl_inst=self.add_inst(name="load",
                                    mod=self.rbl,
                                    offset=self.rbl_offset)
        self.connect_inst(["bl[0]", "br[0]"] + ["gnd"]*self.bitcell_loads + ["vdd", "gnd"])
        



    def route(self):
        """ Connect all the signals together """
        self.route_gnd()
        self.route_vdd()
        self.route_delayed_en()
        self.route_bl()
        self.route_access_tx()
        self.route_enable()
        self.route_output()

    def route_delayed_en(self):
        m1m2_layers = contact.contact.m1m2_layers
        # go down to rail then right to just before gnd rail
        delay_chain_out = self.dc_inst.get_pin("out")
        wl_pin = self.rbc_inst.get_pin("WL")

        rail_x = self.delayed_rail_x + 0.5*self.m1_width

        via_y = self.dc_inst.by() - 0.5*self.inv.rail_height - self.line_end_space - 0.5*contact.m1m2.first_layer_height
        wl_y = wl_pin.cy()

        path = [delay_chain_out.center(),
                vector(delay_chain_out.cx(), via_y)]
        self.add_path("metal2", path)
        self.add_contact_center(m1m2_layers, offset=vector(delay_chain_out.cx(), via_y))

        # create rail
        path = [path[-1], vector(rail_x, via_y), vector(rail_x, wl_y)]
        self.add_path("metal1", path)

        # connect rail to transistor gate
        tx_gate_pin = self.tx_inst.get_pin("G")
        via_y = tx_gate_pin.cy()
        self.add_contact_center(m1m2_layers, offset=vector(rail_x, via_y))
        self.add_contact_center(m1m2_layers, tx_gate_pin.center(), rotate=90)
        gate_height = tx_gate_pin.height()
        area_fill_width = max(utils.ceil(self.minarea_metal1_contact/gate_height), contact.m1m2.first_layer_height)
        self.add_rect_center("metal1", tx_gate_pin.center(), width=area_fill_width, height=gate_height)
        self.add_rect("metal2", offset=tx_gate_pin.center()-vector(0, 0.5*self.m2_width), width=rail_x-tx_gate_pin.cx())

        # connect rail to replica cell wordline
        via_x = wl_pin.lx() - self.m1_space - 0.5*contact.m1m2.first_layer_width
        self.add_contact_center(m1m2_layers, offset=vector(via_x, wl_pin.cy()))
        self.add_rect("metal1", offset=vector(via_x, wl_pin.by()), height=wl_pin.height(), width=wl_pin.lx()-via_x)
        self.add_contact_center(m1m2_layers, offset=vector(rail_x, wl_pin.cy()))
        self.add_rect("metal2", offset=vector(rail_x, wl_pin.by()), width=via_x-rail_x, height=wl_pin.height())

    def route_bl(self):
        a_pin = self.rbl_inv_inst.get_pin("A")
        drain_pin = self.tx_inst.get_pin("D")
        rail_x = self.delayed_rail_x - self.m1_pitch
        # make rail
        self.add_rect("metal1", offset=vector(rail_x, a_pin.cy()), height=drain_pin.cy()-a_pin.cy())
        # drain to rail
        self.add_rect("metal1", offset=vector(drain_pin.cx(), drain_pin.cy()-0.5*self.m1_width),
                      width=rail_x-drain_pin.cx()+self.m1_width)
        # inv input to rail
        self.add_rect("metal1", offset=vector(a_pin.cx(), a_pin.cy()-0.5*self.m1_width),
                      width=rail_x-a_pin.cx()+self.m1_width)

        # rail to bl
        bl_pin = self.rbc_inst.get_pin("BL")
        self.add_rect("metal2", offset=vector(rail_x, drain_pin.cy()-0.5*self.m1_width), width=bl_pin.lx()-rail_x)
        self.add_contact_center(contact.contact.m1m2_layers, offset=vector(rail_x+0.5*contact.m1m2.first_layer_width,
                                                                           drain_pin.cy()))

    def route_access_tx(self):
        # source to rail
        source_pin = self.tx_inst.get_pin("S")
        self.add_rect("metal1", offset=vector(self.left_vdd_offset.x, source_pin.cy()-0.5*self.m1_width),
                      width=source_pin.cx()-self.left_vdd_offset.x)

        # extend inverter nwell

        nwell_top = self.delay_chain_offset.y - self.inverter_delay_chain_space
        nwell_bot = self.rbl_inv_inst.uy()
        nwell_width = self.inv.implant_width

        vdd_pin = self.rbl_inv_inst.get_pin("vdd")

        self.add_rect_center("nwell", offset=vector(vdd_pin.cx(), 0.5*(nwell_bot+nwell_top)),
                             width=nwell_width, height=nwell_top-nwell_bot)

    def route_output(self):
        out_pin = self.rbl_inv_inst.get_pin("Z")
        gnd_pin = self.rbl_inv_inst.get_pin("gnd")

        self.add_rect("metal2", offset=vector(out_pin.lx(), gnd_pin.cy()), height=out_pin.cy()-gnd_pin.cy())
        pin_x = self.gnd_offset.x - self.m1_width - self.parallel_line_space
        self.add_rect("metal2", offset=vector(out_pin.lx(), gnd_pin.cy()), width=pin_x-out_pin.lx())
        via_y = self.fill_height - contact.m1m2.first_layer_height
        self.add_contact(contact.contact.m1m2_layers, offset=vector(pin_x, via_y))
        self.add_rect("metal2", offset=vector(pin_x, via_y), height=gnd_pin.cy()+self.m1_width-via_y)
        self.add_layout_pin("out", "metal1", offset=vector(pin_x, 0), height=via_y)



    def route_enable(self):
        in_pin = self.dc_inst.get_pin("in")
        m1m2_layers = ("metal1", "via1", "metal2")
        self.add_contact_center(layers=m1m2_layers, offset=in_pin.center(), rotate=90)
        mid1_x = self.en_rail_offset + 0.5*self.m1_width
        mid2_x = self.left_vdd_offset.x + self.rail_height + 2*self.line_end_space
        # output pin should fullfill drc requirements


        fill_height = self.fill_height
        self.add_path("metal2", [in_pin.center(), vector(mid1_x, in_pin.cy()), vector(mid1_x, fill_height),
                                 vector(mid2_x+contact.m1m2.second_layer_width, fill_height)])
        self.add_contact(layers=m1m2_layers, offset=vector(mid2_x, fill_height-contact.m1m2.first_layer_height))

        self.add_layout_pin(text="en",
                            layer="metal1",
                            offset=vector(mid2_x, 0),
                            width=self.m1_width,
                            height=fill_height)


        
    def route_vdd(self):
        # Add two vertical rails, one to the left of the delay chain and one to the right of the replica cells

        if self.dc_inst.uy() > self.rbl_inst.uy():
            top = self.dc_inst.uy()
        else:
            m1_rects = (self.replica_bitcell.gds.getShapesInLayer(tech_layers["metal1"]) +
                        body_tap.body_tap().gds.getShapesInLayer(tech_layers["metal1"]))
            top_rect = max(map(lambda x: x[1], map(lambda x: x[1], m1_rects)))
            gnd_extension = top_rect - self.replica_bitcell.height
            top = self.rbl_inst.uy() + gnd_extension
        vdd_height = top + 0.5 * self.rail_height + self.parallel_line_space + self.rail_height

        right_vdd_start = vector(self.rbc_inst.get_pin("gnd").rx() + self.line_end_space, 0)

        # It is the height of the entire RBL and bitcell
        self.right_vdd = self.add_layout_pin(text="vdd",
                            layer="metal1",
                            offset=right_vdd_start,
                            width=self.rail_height,
                            height=vdd_height)

        # Connect the vdd pins of the bitcell load directly to vdd
        vdd_pins = self.rbl_inst.get_pins("vdd")
        for pin in vdd_pins:
            self.add_rect(layer="metal1",
                          offset=pin.lr(),
                          width=right_vdd_start.x-pin.rx()+self.rail_height,
                          height=pin.height())

        # Also connect the replica bitcell vdd pin to vdd
        pin = self.rbc_inst.get_pin("vdd")
        offset = vector(right_vdd_start.x,pin.by())
        self.add_rect(layer="metal1",
                      offset=offset,
                      width=self.bitcell_offset.x-right_vdd_start.x,
                      height=self.rail_height)

        # Add a second vdd pin. No need for full length. It must connect at the next level.
        self.left_vdd = self.add_layout_pin(text="vdd",
                            layer="metal1",
                            offset=vector(0, 0),
                            width=self.rail_height+self.left_vdd_offset.x,
                            height=vdd_height)

        # connect left vdd to right vdd
        self.add_rect("metal1", offset=self.left_vdd.ul() - vector(0, self.rail_height), height=self.rail_height,
                      width=self.right_vdd.rx() - self.left_vdd.lx())

        # Connect the vdd pins of the delay chain
        vdd_pins = self.dc_inst.get_pins("vdd")
        for pin in vdd_pins:
            offset = vector(self.left_vdd_offset.x, pin.by())
            self.add_rect(layer="metal1",
                          offset=offset,
                          width=pin.lx() - self.left_vdd_offset.x,
                          height=self.rail_height)
        inv_pin = self.rbl_inv_inst.get_pin("vdd")
        self.add_rect(layer="metal1",
                      offset=vector(self.left_vdd_offset.x, inv_pin.by()),
                      width=inv_pin.lx() - self.left_vdd_offset.x,
                      height=self.rail_height)

        
        
        
    def route_gnd(self):
        """ Route all signals connected to gnd """

        # It is the height of the entire RBL and bitcell
        self.add_layout_pin(text="gnd",
                            layer="metal1",
                            offset=self.gnd_offset,
                            width=self.rail_height,
                            height=max(self.dc_inst.uy(), self.rbl_inst.uy()))

        # connect bitcell wordlines to gnd
        for row in range(self.bitcell_loads):
            wl = "wl[{}]".format(row)
            pin = self.rbl_inst.get_pin(wl)
            start = vector(self.gnd_offset.x,pin.by())
            self.add_rect(layer="metal1",
                          offset=start,
                          width=pin.lx() - self.gnd_offset.x,
                          height=pin.height())

        # connect replica bit load grounds
        rbl_gnds = self.rbl_inst.get_pins("gnd")
        for pin in rbl_gnds:
            if pin.layer == "metal1":
                self.add_rect(layer="metal1",
                              offset=vector(self.gnd_offset.x, pin.by()),
                              width=pin.lx() - self.gnd_offset.x,
                              height=pin.height())

        # connect replica bit cell to ground
        rbc_gnds = self.rbc_inst.get_pins("gnd")
        for pin in rbc_gnds:
            if pin.layer == "metal1":
                self.add_rect(layer="metal1",
                              offset=vector(self.gnd_offset.x, pin.by()),
                              width=pin.lx() - self.gnd_offset.x,
                              height=pin.height())

        # Connect the gnd pins of the delay chain
        gnd_pins = self.dc_inst.get_pins("gnd")
        for pin in gnd_pins:
            offset = pin.lr()
            self.add_rect(layer="metal1",
                          offset=offset,
                          width=self.gnd_offset.x - offset.x + self.rail_height,
                          height=pin.height())
        inv_pin = self.rbl_inv_inst.get_pin("gnd")
        self.add_rect(layer="metal1",
                      offset=inv_pin.lr(),
                      width=self.gnd_offset.x-inv_pin.rx(),
                      height=inv_pin.height())

        
    def add_lvs_correspondence_points(self):
        """ This adds some points for easier debugging if LVS goes wrong. 
        These should probably be turned off by default though, since extraction
        will show these as ports in the extracted netlist.
        """

        pin = self.rbl_inv_inst.get_pin("A")
        self.add_label_pin(text="bl[0]",
                           layer=pin.layer,
                           offset=pin.ll(),
                           height=pin.height(),
                           width=pin.width())

        pin = self.dc_inst.get_pin("out")
        self.add_label_pin(text="delayed_en",
                           layer=pin.layer,
                           offset=pin.ll(),
                           height=pin.height(),
                           width=pin.width())

