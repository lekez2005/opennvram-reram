# find open space in a module given the layer
from base.utils import round_to_grid
from base.design import design

HORIZONTAL = "horizontal"
VERTICAL = "vertical"


def get_extremities(obj, direction=None):
    if direction == HORIZONTAL:
        extremities = [obj.lx(), obj.rx()]
    else:
        extremities = [obj.by(), obj.uy()]
    return round_to_grid(extremities[0]), round_to_grid(extremities[1])


def get_range_overlap(range_1, range_2):
    range_1 = list(sorted(range_1))
    range_2 = list(sorted(range_2))
    range_1, range_2 = sorted((range_1, range_2), key=lambda x: x[1] - x[0])
    return (range_2[0] <= range_1[0] <= range_2[1] or
            range_2[0] <= range_1[1] <= range_2[1])


def validate_clearances(clearances):
    results = []
    for clearance in clearances:
        if clearance[1] > clearance[0]:
            results.append(clearance)
    return results


def find_clearances(module: design, layer, direction=HORIZONTAL, existing=None, region=None,
                    recursive=True, recursive_insts=None):
    if existing is None:
        edge = module.width if direction == HORIZONTAL else module.height
        existing = [(0, round_to_grid(edge))]
        full_range = existing[0]
    else:
        full_range = (min(map(min, existing)), max(map(max, existing)))
    if region is None:
        edge = module.width if direction == VERTICAL else module.height
        region = (0, round_to_grid(edge))

    rects = module.get_layer_shapes(layer, recursive=recursive)
    if recursive_insts:
        for inst in recursive_insts:
            rects.extend(inst.get_layer_shapes(layer, recursive=True))
    for rect in rects:
        # ensure rect is within considered range
        region_edges = get_extremities(rect, HORIZONTAL if direction == VERTICAL else VERTICAL)
        if not get_range_overlap(region_edges, region):
            continue

        edges = get_extremities(rect, direction)
        if not get_range_overlap(full_range, edges):
            continue

        new_clearances = []
        for clearance in existing:
            if get_range_overlap(clearance, edges):
                if clearance[0] <= edges[0]:
                    new_clearances.extend([(clearance[0], edges[0]), (edges[1], clearance[1])])
                else:
                    new_clearances.append((edges[1], clearance[1]))
            else:
                new_clearances.append(clearance)
        existing = validate_clearances(new_clearances)

    return existing
