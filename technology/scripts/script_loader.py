import argparse
import importlib.util
import os
import subprocess
import sys


def load_module(module_path, module_name):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def latest_scratch():
    scratch = os.path.join(os.environ.get("SCRATCH", "/tmp"), "openram")
    find_results = subprocess.Popen(["find", scratch, "-name", "*.gds",
                                     "-printf", '"%T+ %p\n"'], stdout=subprocess.PIPE)
    sort_results = subprocess.check_output(["sort"], stdin=find_results.stdout).decode()
    find_results.wait()
    latest = sort_results.strip().split("\n")[-1].split()[-1]
    return latest


def load_setup(top_level=False):
    parser = argparse.ArgumentParser()
    parser.add_argument("-t", "--tech", dest="tech_name", help="Technology name",
                        default=os.environ.get("OPENRAM_TECH_NAME"))
    parser.add_argument("-l", "--library", dest="library", help="Library name",
                        default=None)
    parser.add_argument("-c", "--cell_view", dest="cell_view", help="Name of Cell to export",
                        default=None)
    options, other_args = parser.parse_known_args()
    if top_level:
        sys.argv = other_args

    tech_directory = os.environ.get("OPENRAM_TECH")
    tech_name = options.tech_name
    setup_path = os.path.join(tech_directory, tech_name, "tech", "setup_openram.py")
    setup = load_module(setup_path, "setup")
    if top_level and options.library is not None:
        setup.export_library_name = options.library
    return setup, tech_name, options
