import io
from typing import List

from base.design import design
from base.geometry import geometry, rectangle
from base.pin_layout import pin_layout

InstList = List[geometry]
IntList = List[int]


def export_spice(cell: design):
    sp = io.StringIO('')
    cell.sp_write_file(sp, [])
    flatten_subckts(cell)
    sp.seek(0)
    cell.spice = sp.read().split('\n')


def set_default_insts(self, insts: InstList, inst_indices: IntList):
    if insts is None:
        inst_indices, insts = list(range(len(self.insts))), self.insts
    if inst_indices is None:
        inst_indices = list(range(len(insts)))
    return insts, inst_indices


def flatten_rects(self: design, insts: InstList = None,
                  inst_indices: IntList = None):
    """Move rects in insts to top-level 'self' """

    insts, inst_indices = set_default_insts(self, insts, inst_indices)

    # first export spice if any of the insts has spice connections
    should_export = False
    for conn_index in inst_indices:
        if self.conns[conn_index]:
            should_export = True
    if should_export:
        export_spice(self)

    flat_rects = self.get_layer_shapes(layer=None, recursive=True, insts=insts)
    other_obj = [x for x in self.objs if not isinstance(x, rectangle)]

    # turn pins to rects
    pin_indices = []
    for shape_index, shape in enumerate(flat_rects):
        if isinstance(shape, pin_layout):
            self.add_rect(shape.layer, shape.ll(), width=shape.width(),
                          height=shape.height())
            pin_indices.append(shape_index)
    flat_rects = [rect for pin_index, rect in enumerate(flat_rects) if pin_index not in pin_indices]

    self.objs = other_obj + flat_rects

    self.insts = [inst for inst_index, inst in enumerate(self.insts)
                  if inst_index not in inst_indices]
    self.conns = [conn for conn_index, conn in enumerate(self.conns)
                  if conn_index not in inst_indices]


def flatten_subckts(self: design, insts: InstList = None,
                    inst_indices: IntList = None):
    insts, inst_indices = set_default_insts(self, insts, inst_indices)
    for inst in insts:
        flatten_rects(inst.mod)
