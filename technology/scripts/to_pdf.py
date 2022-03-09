#!/bin/env python

import os
import sys

sys.path.append(os.environ["OPENRAM_HOME"])  # for gdsMill

try:
    from script_loader import load_setup, load_module, latest_scratch
except (ImportError, ModuleNotFoundError):
    from .script_loader import load_setup, load_module, latest_scratch


def setup_tech(top_level=False):
    setup, tech_name, options = load_setup(top_level=top_level)
    tech_mod = os.path.join(os.environ["OPENRAM_TECH"], tech_name, "tech", "tech.py")
    return load_module(tech_mod, "tech"), setup, options


def export_pdf(gds, tech):
    from gdsMill import gdsMill
    from gdsMill.gdsMill.pdfLayout import pdfLayout, OUTLINE, FILL, DASHED, STRIPE

    layout = gdsMill.VlsiLayout()
    gdsMill.Gds2reader(layout).loadFromFile(gds)

    visualizer = pdfLayout(layout)

    layers = {
        "boundary": ("#9900e6", DASHED),
        "pwell": ("#ffff00", OUTLINE),
        "nwell": ("#00ccf2", OUTLINE),
        "nimplant": ("#5e00e6", OUTLINE),
        "pimplant": ("#ff8000", OUTLINE),
        "poly": ("#ff0000", FILL),
        "active": ("#00cc66", FILL),
        "metal1": ("#0000ff", STRIPE),
        "metal2": ("#ff00ff", STRIPE),
        "metal3": ("#00ffff", STRIPE, 0.3),
        "metal4": ("#f58d42", STRIPE, 0.3),
        "contact": ("#aaaaaa", FILL),
        "via1": ("#ff00ff", FILL),
        "via2": ("#39bfff", FILL),
        "via3": ("#ffe6bf", FILL)
    }
    layers["active_contact"] = layers["active"]
    if hasattr(tech, "layer_colors"):
        layers.update(tech.layer_colors)

    for layer_num in layout.layerNumbersInUse:
        layer_name = [key for key, value in tech.layer.items() if value == layer_num]
        if not layer_name and hasattr(tech, "layer_pin_map"):
            layer_num = [key for key, value in tech.layer_pin_map.items() if value == layer_num]
            if layer_num:
                layer_num = layer_num[0]
                layer_name = [key for key, value in tech.layer.items() if value == layer_num]
        if not layer_name:
            continue
        layer_name = layer_name[0]
        if layer_name not in layers:
            print(layer_name)
        layer_def = layers.get(layer_name, (visualizer.randomHexColor(), STRIPE))
        visualizer.layerColors[layer_num] = layer_def

    visualizer.setScale(100)
    visualizer.transparency = 0.3
    visualizer.drawLayout()
    svg_file = os.path.splitext(gds)[0] + ".svg"
    pdf_file = os.path.splitext(gds)[0] + ".pdf"
    visualizer.writeSvgFile(svg_file)
    visualizer.writeToFile(pdf_file)
    print(svg_file)


if __name__ == "__main__":
    tech_, setup_, options_ = setup_tech(top_level=True)
    if len(sys.argv) > 0 and sys.argv[0].endswith(".gds"):
        gds_ = sys.argv[0]
    elif options_.cell_view or len(sys.argv) > 0:
        cell_view = options_.cell_view or sys.argv[0]
        to_gds = load_module(os.path.join(os.path.dirname(__file__), "to_gds.py"),
                             "to_gds")
        library_ = options_.library or setup_.import_library_name
        output_dir = os.path.join(os.environ["SCRATCH"], "openram")
        gds_ = to_gds.export_gds(library_, [cell_view], output_dir, setup_)[0]
    else:
        gds_ = latest_scratch()
    export_pdf(gds_, tech_)
