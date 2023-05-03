import itertools
import os
from xml.etree import ElementTree

import debug
from base import utils
from globals import OPTS


def run_klayout(command_name, cell_name, rule_file, options):
    command = f"{OPTS.drc_exe[1]} -b -r {rule_file} {options}"
    err_file = os.path.join(OPTS.openram_temp, f"{cell_name}.{command_name}.err")
    out_file = os.path.join(OPTS.openram_temp, f"{cell_name}.{command_name}.out")

    return_code = utils.run_command(command, stdout_file=out_file, stderror_file=err_file,
                                    verbose_level=2, cwd=OPTS.openram_temp)
    return return_code, out_file, err_file


def get_output_file(cell_name, gds_name, command_name):
    output_dir = os.path.dirname(gds_name)
    return os.path.join(output_dir, f"{cell_name}.{command_name}.report")


def create_options_str(cell_name, gds_name, command_name):
    report_file = get_output_file(cell_name, gds_name, command_name)
    report_name = getattr(OPTS, "klayout_report_name", "output")
    options = {"topcell": cell_name, "input": gds_name, report_name: report_file}
    if hasattr(OPTS, "klayout_drc_options"):
        options.update(OPTS.klayout_drc_options)
    return " ".join([f"-rd {key}={value}" for key, value in options.items()]), report_file


class DrcError:
    def __init__(self, item_node):
        self.cell = item_node.find('cell').text
        self.category = item_node.find('category').text.replace("'", "")
        self.multiplicity = int(item_node.find('multiplicity').text)
        self.values = item_node.find("values")

    @staticmethod
    def parse_rules(tree):
        rules = tree.getroot().findall('./categories/category')
        for rule in rules:
            yield rule.find("name").text, rule.find("description").text

    @staticmethod
    def get_drc_exceptions(exception_group):
        from tech import drc_exceptions
        ignored = drc_exceptions.get(exception_group, [])
        ignored += drc_exceptions.get("all", [])
        return ignored

    @staticmethod
    def parse_errors(report_file, exception_group):
        ignored = DrcError.get_drc_exceptions(exception_group)

        tree = ElementTree.parse(report_file)
        rules = {key: value for key, value in DrcError.parse_rules(tree)}
        errors = map(DrcError, tree.getroot().findall('./items/item'))
        errors = [x for x in errors if x.category not in ignored]

        errors = sorted(errors, key=lambda x: x.cell)
        for cell, cell_errors in itertools.groupby(errors, key=lambda x: x.cell):
            cell_errors = sorted(cell_errors, key=lambda x: x.category)
            print(f"cell: {cell}")
            for category, category_errors in itertools.groupby(cell_errors, key=lambda x: x.category):
                category_errors = list(category_errors)
                num_errors = (str(len(category_errors)) + " " * 5)[:5]
                print(f"\t {num_errors}  {rules[category]}")
                if OPTS.debug_level > 1:
                    for category_error in category_errors:
                        for value in category_error.values.findall("value"):
                            print(f"\t\t\t\t {value.text}")
        return len(errors)


def run_drc(cell_name, gds_name, exception_group="", flatten=None):
    debug.info(1, f"Running DRC for cell {cell_name}")
    command_name = "drc"
    options, report_file = create_options_str(cell_name, gds_name, command_name)
    rule_file = os.environ.get("KLAYOUT_DRC_DECK")
    assert os.path.exists(rule_file), f"DRC rules file {rule_file} does not exist"
    return_code, out_file, err_file = run_klayout(command_name, cell_name, rule_file, options)
    from .magic import check_process_errors
    debug.error(f"{command_name} return code is non-zero", return_code)
    benign_errors = DrcError.get_drc_exceptions(exception_group)
    check_process_errors(err_file, command_name, benign_errors=benign_errors)

    num_errors = DrcError.parse_errors(report_file, exception_group)
    if num_errors > 0:
        debug.error("DRC Errors {0}\t{1}".format(cell_name, num_errors))
    else:
        debug.info(1, "No DRC Error")

    return num_errors
