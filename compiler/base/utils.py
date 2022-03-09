import importlib.util
import json
import math
import os
import random
import subprocess
import time
from functools import lru_cache
from importlib import reload
from typing import List, TYPE_CHECKING

import globals
import tech
from base.geometry import rectangle
from base.pin_layout import pin_layout
from base.vector import vector
from gdsMill import gdsMill

try:
    from tech import layer_pin_map
except ImportError:
    layer_pin_map = {}

OPTS = globals.OPTS
round_scale = 10000


def ceil(decimal):
    """
    Performs a ceiling function on the decimal place specified by the DRC grid.
    """
    decimal = round(decimal * round_scale) / round_scale
    grid = tech.drc["grid"]
    return math.ceil(decimal * 1 / grid) / (1 / grid)


def ceil_2x_grid(decimal):
    """
    Performs a ceiling function on the decimal place specified by the DRC grid.
    Such that it remains on grid when divided by 2
    """
    round(decimal * round_scale) / round_scale
    grid = tech.drc["grid"] * 2
    return math.ceil(decimal * 1 / grid) / (1 / grid)


def floor_2x_grid(decimal):
    """
    Performs a ceiling function on the decimal place specified by the DRC grid.
    Such that it remains on grid when divided by 2
    """
    round(decimal * round_scale) / round_scale
    grid = tech.drc["grid"] * 2
    return math.floor(decimal * 1 / grid) / (1 / grid)


def floor(decimal):
    """
    Performs a flooring function on the decimal place specified by the DRC grid.
    """
    round(decimal * round_scale) / round_scale
    grid = tech.drc["grid"]
    return math.floor(decimal * 1 / grid) / (1 / grid)


@lru_cache(maxsize=64)
def round_to_grid(number):
    """
    Rounds an arbitrary number to the grid.
    """
    grid = tech.drc["grid"]  
    # this gets the nearest integer value
    # 0.001 added for edge cases: round(196.5, 0) rounds to 196 in python3 but 197 in python 2
    number_grid = int(math.copysign(1, number) * round(round((abs(number) / grid), 2) + 0.001, 0))
    number_off = number_grid * grid
    return number_off

def snap_to_grid(offset):
    """
    Changes the coodrinate to match the grid settings
    """
    return [round_to_grid(offset[0]),round_to_grid(offset[1])]

def pin_center(boundary):
    """
    This returns the center of a pin shape in the vlsiLayout border format.
    """
    return [0.5 * (boundary[0] + boundary[2]), 0.5 * (boundary[1] + boundary[3])]

def pin_rect(boundary):
    """
    This returns a LL,UR point pair.
    """
    return [vector(boundary[0],boundary[1]),vector(boundary[2],boundary[3])]


def transform(pos, offset, mirror, rotate):
    if mirror == "MX":
        pos = pos.scale(1, -1)
    elif mirror == "MY":
        pos = pos.scale(-1, 1)
    elif mirror == "XY":
        pos = pos.scale(-1, -1)

    if rotate == 90:
        pos = pos.rotate_scale(-1, 1)
    elif rotate == 180:
        pos = pos.scale(-1, -1)
    elif rotate == 270:
        pos = pos.rotate_scale(1, -1)

    return pos + offset


def transform_relative(pos, inst):
    return transform(pos, offset=inst.offset, mirror=inst.mirror, rotate=inst.rotate)


def get_pin_rect(pin, instances):
    first = pin.ll()
    second = pin.ur()
    for instance in reversed(instances):
        (first, second) = map(lambda x: transform_relative(x, instance), [first, second])
    ll = [min(first[0], second[0]), min(first[1], second[1])]
    ur = [max(first[0], second[0]), max(first[1], second[1])]
    return ll, ur

def get_body_tap():
    from modules import body_tap as mod_body_tap

    body_tap = mod_body_tap.body_tap
    return body_tap()

def get_tap_positions(num_columns):
    # cells_per_group to accommodate peripherals spanning more than one bitcell.
    # bitcell positions are calculated such that bitcells are only appended at the beginning
    # of groups and not in the middle
    c = __import__(OPTS.bitcell)
    bitcell = getattr(c, OPTS.bitcell)()

    cells_per_group = OPTS.cells_per_group

    if not OPTS.use_x_body_taps:
        bitcell_offsets = [i*bitcell.width for i in range(num_columns)]
        return bitcell_offsets, []

    body_tap = get_body_tap()

    cells_spacing = int(math.ceil(0.9*tech.drc["latchup_spacing"]/bitcell.width))  # 0.9 for safety
    cells_spacing = cells_spacing - (cells_spacing % cells_per_group)

    tap_width = body_tap.width
    i = 0
    tap_positions = []
    while i <= num_columns:
        tap_positions.append(i)
        i += cells_spacing
    if tap_positions[-1] == num_columns:
        tap_positions[-1] = num_columns - cells_per_group  # prevent clash with cells to the right of bitcell array

    preliminary_array_width = num_columns * bitcell.width + len(tap_positions) * tap_width
    right_buffers_x = OPTS.repeater_x_offset * preliminary_array_width

    # determine whether space needs to be opened up for repeaters and how much space is needed
    add_repeaters = (OPTS.add_buffer_repeaters and
                     num_columns > OPTS.buffer_repeaters_col_threshold and
                     len(OPTS.buffer_repeater_sizes) > 0)
    add_buffers_rails_space = add_repeaters and OPTS.dedicated_repeater_space

    if add_repeaters and not OPTS.dedicated_repeater_space:
        OPTS.buffer_repeaters_x_offset = right_buffers_x

    rails_num_taps = 0
    if add_buffers_rails_space:
        from base.design import design
        output_nets = [x[1] for x in OPTS.buffer_repeater_sizes]
        flattened_nets = [x for y in output_nets for x in y]
        num_rails = len(flattened_nets)
        m4_space = design.get_parallel_space("metal4")
        m4_pitch = max(design.get_min_layer_width("metal4"),
                       design.get_bus_width()) + m4_space
        rails_num_taps = math.ceil((num_rails * m4_pitch + m4_space) / tap_width)
        OPTS.repeaters_space_num_taps = rails_num_taps

    tap_positions = list(sorted(set(tap_positions)))
    x_offset = 0.0
    positions_index = 0
    bitcell_offsets = [None]*num_columns
    tap_offsets = []

    OPTS.repeaters_array_space_offsets = []

    for i in range(num_columns):
        if positions_index < len(tap_positions) and i == tap_positions[positions_index]:
            tap_offsets.append(x_offset)
            x_offset += tap_width
            positions_index += 1
        bitcell_offsets[i] = x_offset
        x_offset += bitcell.width
        if add_buffers_rails_space:
            if x_offset > right_buffers_x and (i + 1) % cells_per_group == 0:
                OPTS.buffer_repeaters_x_offset = x_offset
                OPTS.repeaters_array_space_offsets = [x_offset + i * tap_width for i in range(rails_num_taps)]
                x_offset += rails_num_taps * tap_width
                add_buffers_rails_space = False
    return bitcell_offsets, tap_offsets


def get_body_tap_width():
    from modules.body_tap import body_tap
    return body_tap().width


def get_random_vector(word_size):
    return [int(random.uniform(0, 1) > 0.5) for _ in range(word_size)]


def auto_measure_libcell(pin_list, name, units, layer):
    """
    Open a GDS file and find the pins in pin_list as text on a given layer.
    Return these as a set of properties including the cell width/height too.
    """
    cell_gds = os.path.join(OPTS.openram_tech, "gds_lib", str(name) + ".gds")
    cell_vlsi = gdsMill.VlsiLayout(units=units, from_file=cell_gds)
    cell_vlsi.load_from_file()

    cell = {}
    measure_result = cell_vlsi.getLayoutBorder(layer)
    if measure_result == None:
        measure_result = cell_vlsi.measureSize(name)
    [cell["width"], cell["height"]] = measure_result

    for pin in pin_list:
        (name,layer,boundary)=cell_vlsi.getPinShapeByLabel(str(pin))        
        cell[str(pin)] = pin_center(boundary)
    return cell


def load_gds(name, units):
    if os.path.isabs(name) and os.path.exists(name):
        cell_gds = name
    else:
        cell_gds = os.path.join(OPTS.openram_tech, "gds_lib", str(name) + ".gds")
    cell_vlsi = gdsMill.VlsiLayout(units=units, from_file=cell_gds)
    cell_vlsi.load_from_file()
    return cell_vlsi


def get_libcell_size(name, units, layer):
    """
    Open a GDS file and return the library cell size from either the
    bounding box or a border layer.
    """
    cell_vlsi = load_gds(name, units)

    measure_result = cell_vlsi.getLayoutBorder(layer)
    if measure_result == None:
        name = name.split("/")[-1]
        measure_result = cell_vlsi.measureSize(name)
    # returns width,height
    return measure_result


def get_libcell_pins(pin_list, name, units=None, layer=None, cell_vlsi=None):
    """
    Open a GDS file and find the pins in pin_list as text on a given layer.
    Return these as a rectangle layer pair for each pin.
    """
    if units is None:
        units = tech.GDS["unit"]
    if layer is None:
        layer = tech.layer["boundary"]
    cell_vlsi = cell_vlsi or load_gds(name, units)

    cell = {}
    for pin in pin_list:
        cell[str(pin).lower()]=[]
        label_list=cell_vlsi.getPinShapeByLabel(str(pin), layer_pin_map=layer_pin_map)
        for label in label_list:
            (name,layer,boundary)=label
            rect = pin_rect(boundary)
            # this is a list because other cells/designs may have must-connect pins
            cell[str(pin).lower()].append(pin_layout(pin, rect, layer))
    return cell


def get_clearances(cell, layer, purpose=None):
    all_rects = list(sorted(cell.get_gds_layer_rects(layer, purpose),
                            key=lambda x: x.height))  # type: List[rectangle]

    def remove_empty(rects):
        return list(filter(lambda rect: rect[1] > rect[0], rects))

    height = cell.height
    if len(all_rects) == 0:
        return [(0, height)]
    elif len(all_rects) == 1:
        top_rect = all_rects[0]
        return remove_empty([(0, top_rect.by()), (top_rect.uy(), height)])



    def overlaps(rect1, rect2):
        return rect1.by() <= rect2.by() <= rect1.uy() or rect2.by() <= rect1.by() <= rect2.uy()

    def combine_rects(original, rect2):
        original.boundary = [vector(original.lx(), min(original.by(), rect2.by())),
                             vector(original.rx(), max(original.uy(), rect2.uy()))]

    def find_overlaps(rects):
        original_length = len(rects)
        obstructions = [rects[0]]
        for rect in rects[1:]:
            found = False
            for obstruction in obstructions:
                if overlaps(rect, obstruction):
                    combine_rects(obstruction, rect)
                    found = True
                    break
            if not found:
                obstructions.append(rect)
        final_length = len(obstructions)
        return original_length == final_length, obstructions

    obstructions = all_rects
    while True:
        stabilized, obstructions = find_overlaps(obstructions)
        if stabilized:
            break
    obstructions = list(sorted(obstructions, key=lambda x: x.by()))

    results = []
    prev_top = 0
    for obstruction in obstructions:
        results.append((prev_top, obstruction.by()))
        prev_top = obstruction.uy()
    results.append((prev_top, height))

    return remove_empty(results)


def load_class(class_name):
    config_mod_name = getattr(OPTS, class_name)
    class_file = reload(__import__(config_mod_name))
    return getattr(class_file, config_mod_name)


def run_command(command, stdout_file, stderror_file, verbose_level=1, cwd=None):
    import debug

    pre_exec_fcn = None
    try:
        import psutil
        nice_value = os.getenv("OPENRAM_SUBPROCESS_NICE", 15)
        if nice_value:
            def pre_exec_fcn():
                pid = os.getpid()
                ps = psutil.Process(pid)
                ps.nice(int(nice_value))
    except ImportError:
        pass

    verbose = OPTS.debug_level >= verbose_level
    if cwd is None:
        cwd = OPTS.openram_temp
    with open(stdout_file, "w") as stdout_f, open(stderror_file, "w") as stderr_f:
        stdout = subprocess.PIPE if verbose else stdout_f
        stderr = subprocess.STDOUT if verbose else stderr_f
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr, shell=True,
                                   cwd=cwd, preexec_fn=pre_exec_fcn)
        while verbose:
            line = process.stdout.readline().decode()
            if not line:
                process.stdout.close()
                break
            else:
                debug.print_str(line.rstrip())
                stdout_f.write(line)

    if process is not None:
        while process.poll() is None:
            # Process hasn't exited yet, let's wait some
            time.sleep(0.5)
        return process.returncode
    else:
        return -1


def get_temp_file(file_name):
    return os.path.join(OPTS.openram_temp, file_name)


def get_sorted_metal_layers():
    layers = [x for x in tech.layer.keys() if x.startswith("metal")]
    layers = sorted(layers, key=lambda x: int(x[5:]))
    layer_numbers = [int(x[5:]) for x in layers]
    return list(layers), layer_numbers


def write_json(data, file_name):
    if not os.path.isabs(file_name):
        file_name = os.path.join(OPTS.openram_temp, file_name)
    with open(file_name, "w") as f:
        json.dump(data, f, indent=4, sort_keys=True)


def load_module(path):
    """Load module given absolute path"""
    mod_name = os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(mod_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def to_cadence(gds_file):
    abs_path = os.path.dirname(os.path.abspath(__file__))
    file_dir = os.path.join(abs_path, '..', '..', 'technology', 'scripts')
    file_path = os.path.join(file_dir, 'to_cadence.py')
    to_cadence_ = load_module(file_path)
    to_cadence_.export_gds(gds_file)


class BaseMixin:
    pass


def run_time_mixin():
    """if not running type checks, return empty BaseMixin class"""
    if TYPE_CHECKING:
        return None
    return BaseMixin
