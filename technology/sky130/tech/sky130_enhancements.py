import debug
from base import contact
from base.design import design, POLY, ACTIVE
from base.flatten_layout import flatten_rects
from base.vector import vector
from tech import drc


def get_vias(obj: design):
    return [x for x in enumerate(obj.insts) if isinstance(x[1].mod, contact.contact)]


def add_stdc(obj: design):
    """Add stdc around active rects"""
    active_rects = obj.get_layer_shapes(ACTIVE)
    for rect in active_rects:
        obj.add_rect("stdc", rect.ll(), width=rect.width, height=rect.height)


def seal_poly_vias(obj: design):
    """Add npc around poly contacts"""
    poly_via_insts = [x[1] for x in get_vias(obj) if x[1].mod.layer_stack[0] == POLY]
    if not poly_via_insts:
        return
    debug.info(2, f"Sealing Poly vias in module {obj.name}")

    sample_via = poly_via_insts[0].mod

    npc_enclose_poly = drc.get("npc_enclose_poly")
    npc_space = 0.27

    center_to_edge = 0.5 * sample_via.contact_width + npc_enclose_poly

    poly_via_insts = list(sorted(poly_via_insts, key=lambda x: (x.lx(), x.by())))

    # group vias that are close together

    def enclose_cont(via_inst_):
        left = via_inst_.cx() - center_to_edge
        right = via_inst_.cx() + center_to_edge
        bottom = via_inst_.cy() - center_to_edge
        top = via_inst_.cy() + center_to_edge
        return [left, right, bottom, top]

    via_groups = []
    for via_inst in poly_via_insts:
        found = False
        for via_group in via_groups:
            (left_x, right_x, bot_y, top_y, existing_insts) = via_group
            span_left = left_x - npc_space
            span_right = right_x + npc_space
            span_top = top_y + npc_space
            span_bot = bot_y - npc_space

            left_, right_, bottom_, top_ = enclose_cont(via_inst)

            if span_left <= left_ <= span_right or span_left <= right_ <= span_right:
                if span_bot <= bottom_ <= span_top or span_bot <= top_ <= span_top:
                    existing_insts.append(via_inst)
                    via_group[0] = min(left_x, left_)
                    via_group[1] = max(right_x, right_)
                    via_group[2] = min(bot_y, bottom_)
                    via_group[3] = max(top_y, top_)
                    found = True
                    break

        if not found:
            via_groups.append([*enclose_cont(via_inst), [via_inst]])

    class_name = obj.__class__.__name__
    for left_, right_, bot_, top_, _ in via_groups:
        if class_name == "reram_bitcell":
            height = obj.height - bot_  # no space between adjacent bitcells
        else:
            height = top_ - bot_
        # prevent minimum space between adjacent cells
        if left_ < 0.5 * npc_space:
            left_ = 0
        if right_ > obj.width - 0.5 * npc_space:
            right_ = obj.width
        obj.add_rect("npc", vector(left_, bot_), width=right_ - left_, height=height)


def flatten_vias(obj: design):
    """Flatten vias by moving via shapes from via instance to top level
    """
    debug.info(2, f"Flattening vias in module {obj.name}")
    all_via_inst = get_vias(obj)
    all_via_index = [x[0] for x in all_via_inst]
    insts = [x[1] for x in all_via_inst]
    flatten_rects(obj, insts, all_via_index)


def enhance_module(obj: design):
    if getattr(obj, "sky_130_enhanced", False):
        return

    debug.info(2, f"Enhancing module {obj.name}")
    obj.sky_130_enhanced = True
    # add stdc and seal poly before flattening vias
    add_stdc(obj)
    seal_poly_vias(obj)
    flatten_vias(obj)
