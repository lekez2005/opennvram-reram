"""
This is a DRC/LVS/PEX interface file for magic + netgen.
"""

import os
import pathlib
import re
import shutil
import subprocess

import debug

# for exporting from gds to mag
magic_template = """
drc off
set VDD vdd
set GND gnd
set SUB gnd
# gds polygon subcells yes
gds warning default
{gds_flatten}
{gds_options}
gds ordering true
gds readonly true
gds read "{gds_file}"
puts "Finished reading gds {gds_file}"
{load_command}
cellname delete \\(UNNAMED\\)
### additional commands
{other_commands}
### commands
exit
"""

# for running drc
drc_template = """
select top cell
expand
{flatten_command}
select top cell
puts "Finish Expand and select"
drc style drc(full)
drc euclidean on
drc check
drc catchup
drc count total
puts "Finished DRC"
puts "###begin-descriptions"
select top cell
drc why
"""

# generating layout spice for netgen
spice_gen_template = """
drc off
load "{mag_file_}"
select top cell
{make_ports}
{extract_unique}
{extract_style}
{flatten_command}
extract
puts "Finished lvs layout extraction"
ext2spice subcircuit top on
ext2spice hierarchy on
ext2spice scale off
ext2spice format ngspice
ext2spice cthresh infinite
ext2spice rthresh infinite:q
ext2spice renumber off
ext2spice global off
ext2spice {cell_name_}{flat_suffix} -o {cell_name_}.spice
puts "Finished spice export"
exit
"""

# netgen lvs script
netgen_template = """
#!/env sh
{netgen_exe} -noconsole << EOF
lvs {{{source_spice} {cell_name_} }} {{{layout_spice} {lvs_cell_name}}} {setup_file} {report_file} -full -json
quit
EOF
retcode=$?
exit $retcode
"""

# PEX extraction script
pex_template = """
load "{mag_file_}"
flatten "{cell_name_}_flat"
load "{cell_name_}_flat"
select top cell
extract all
ext2sim labels on
ext2sim
extresist simplify off
extresist
ext2spice lvs
ext2spice format ngspice
ext2spice scale off
ext2spice cthresh 0
ext2spice rthresh 0
# ext2spice extresist on
ext2spice -d "{cell_name_}_flat" -o {output_file}
puts "Finished extraction export"
exit
"""


def get_run_script(op_name):
    from globals import OPTS
    work_dir = OPTS.openram_temp
    return os.path.join(work_dir, f"setup_{op_name}.tcl")


def generate_magic_script(gds, cell_name, flatten, op_name, template=None, **kwargs):
    from globals import OPTS
    template = template or magic_template
    gds_file = os.path.abspath(gds)

    work_dir = OPTS.openram_temp
    pathlib.Path(work_dir).mkdir(parents=True, exist_ok=True)
    magic_rc = os.environ.get("MAGIC_RC")

    magic_rc_dest = os.path.join(work_dir, ".magicrc")
    os.system(f"cp {magic_rc} {magic_rc_dest}")

    kwargs["cell_name"] = cell_name
    kwargs["gds_file"] = gds_file
    kwargs["gds_flatten"] = "gds flatten true" * flatten
    if cell_name:
        load_command = f'load {cell_name} \nputs "Loaded cell {cell_name}"'
    else:
        load_command = ""
    kwargs["load_command"] = load_command

    kwargs.setdefault("other_commands", "")
    kwargs.setdefault("gds_options", "")

    setup_script = get_run_script(op_name)

    with open(setup_script, "w") as f:
        f.write(template.format(**kwargs))
    return setup_script


def get_force_reload_commands(cell_name):
    full_mag_file = os.path.join(os.path.dirname(get_run_script("drc")), f"{cell_name}.mag")
    reference_name = full_mag_file[:-4]
    commands = [f"load \"{full_mag_file}\" -force",
                f'cellname dereference "{reference_name}"',
                "select top cell",
                "expand",
                f'cellname writeable "{reference_name}" false']
    return commands


def get_refresh_command(cell_name):
    if not cell_name or "MAGIC_WORK_DIR" not in os.environ:
        return ""
    ipc_file = os.path.join(os.environ.get("MAGIC_WORK_DIR"), "ipc_file.txt")
    if os.path.exists(ipc_file):
        with open(ipc_file, 'r') as f:
            ipc, pid = f.read().strip().split()
            # https://stackoverflow.com/a/20186516
            try:
                os.kill(int(pid), 0)
            except ProcessLookupError:  # errno.ESRCH
                return ""  # No such process

        cmd = f"package require comm\n"
        for command in get_force_reload_commands(cell_name):
            cmd += f"::comm::comm send {ipc} {command}\n"
        return cmd
    return ""


def run_subprocess(script_file_name):
    tmp_dir = os.path.dirname(script_file_name)
    command = f"magic -dnull -noconsole {script_file_name}"
    return subprocess.call(command.split(), cwd=tmp_dir)


def export_gds_to_magic(gds_file, cell_name=None, flatten=False):
    refresh_command = get_refresh_command(cell_name)
    kwargs = {
        "other_commands": "writeall force\n" + refresh_command
    }
    script = generate_magic_script(gds_file, cell_name, flatten, "export", **kwargs)
    return_code = run_subprocess(script)
    return return_code, script


def run_script(script_file_name, cell_name, op_name, command_template=None):
    from globals import OPTS
    err_file = os.path.join(OPTS.openram_temp, f"{cell_name}.{op_name}.err")
    out_file = os.path.join(OPTS.openram_temp, f"{cell_name}.{op_name}.out")
    from base import utils
    if not command_template:
        command_template = "magic -dnull -noconsole {script_file_name}"
    command = command_template.format(script_file_name=script_file_name)
    debug.info(2, command)
    return_code = utils.run_command(command, stdout_file=out_file, stderror_file=err_file,
                                    verbose_level=2, cwd=OPTS.openram_temp)
    return return_code, out_file, err_file


def check_process_errors(err_file, op_name, benign_errors=None):
    if benign_errors is None:
        benign_errors = []
    benign_errors = [re.compile(x, re.IGNORECASE) for x in benign_errors]
    with open(err_file, "r") as f:
        errors = f.read()
        if errors:
            for line in errors.split("\n"):
                if not line:
                    continue
                benign = False
                for regex in benign_errors:
                    if regex.search(line):
                        benign = True
                        break
                if not benign:
                    debug.error(f"{op_name} Errors: {errors}")


def run_drc(cell_name, gds_name, exception_group="", flatten=None):
    """Run DRC check on a cell which is implemented in gds_name."""
    from globals import OPTS
    from tech import drc_exceptions
    debug.info(1, f"Running DRC for cell {cell_name}")

    flatten = getattr(OPTS, "flat_drc", True)

    if flatten:
        drc_cell_name = f"{cell_name}_flat"
        flatten_command = f'flatten "{drc_cell_name}"\nload "{drc_cell_name}"\n' \
                          f'writeall force "{drc_cell_name}"\n'
    else:
        drc_cell_name = cell_name
        flatten_command = "writeall force\nexpand"
    drc_cell_name = os.path.join(os.path.dirname(gds_name), drc_cell_name)
    refresh_command = get_refresh_command(drc_cell_name)

    drc_command = drc_template.format(flatten_command=flatten_command)
    kwargs = {"other_commands": drc_command + refresh_command}
    script = generate_magic_script(gds_name, cell_name, True, "drc", **kwargs)
    return_code, out_file, err_file = run_script(script, cell_name, "drc")

    check_process_errors(err_file, "DRC")

    with open(out_file, "r") as f:
        results = f.readlines()

    # those lines should be the last 3
    errors = 0
    for line in reversed(results):
        if "Total DRC errors found:" in line:
            errors += int(re.split(": ", line)[1])

    valid_drc_errors = []
    if errors > 0:
        # print error descriptions
        split_output = "".join(results).split("###begin-descriptions")

        if len(split_output) == 2 and split_output[1].strip():
            all_descriptions = split_output[1].strip().split("\n")
            for description in all_descriptions:
                ignore_error = False
                if exception_group in drc_exceptions:
                    for exception in drc_exceptions[exception_group]:
                        if description == exception:
                            ignore_error = True
                            break
                if ignore_error:
                    debug.warning("Ignoring DRC error: %s", description)
                else:
                    valid_drc_errors.append(description)
        for line in results:
            if "error tiles" in line:
                debug.info(1, line.rstrip("\n"))
    if len(valid_drc_errors) > 0:
        debug.info(1, "\n".join(valid_drc_errors))
        debug.error("DRC Errors {0}\t{1}".format(cell_name, errors))
    else:
        debug.info(1, "No DRC Error")

    return len(valid_drc_errors)


def get_lvs_kwargs(cell_name, mag_file, source_spice, final_verification, flatten):
    from globals import OPTS
    if source_spice:
        make_ports = f"readspice \"{source_spice}\""
    else:
        make_ports = "port makeall"
    extract_unique = "extract unique all" * final_verification
    extract_style = getattr(OPTS, "lvs_extract_style", "")

    if flatten:
        flatten_command = f"flatten {cell_name}_flat\nload {cell_name}_flat"
    else:
        flatten_command = ""

    kwargs = {
        "make_ports": make_ports,
        "extract_unique": extract_unique,
        "extract_style": extract_style,
        "cell_name_": cell_name,
        "mag_file_": mag_file,
        "flatten_command": flatten_command,
        "flat_suffix": "_flat"*flatten
    }
    return kwargs


def generate_lvs_spice(mag_file, source_spice, final_verification=False, flatten=False):
    debug.info(1, f"Generating layout spice")
    cell_name = os.path.basename(mag_file)[:-4]
    kwargs = get_lvs_kwargs(cell_name, mag_file, source_spice, final_verification,
                            flatten=flatten)
    extract_script = generate_magic_script(mag_file, cell_name, flatten=False,
                                           op_name="spice_gen",
                                           template=spice_gen_template, **kwargs)
    return_code, out_file, err_file = run_script(extract_script, cell_name, "spice_gen")
    benign_errors = ["Couldn't find label", r"Total of \d+ warnings."]
    check_process_errors(err_file, "gen_spice", benign_errors=benign_errors)
    debug.info(1, f"Generated layout spice")
    return return_code, out_file, err_file


def run_netgen(cell_name, lvs_cell_name, layout_spice, source_spice):
    """ Write a netgen script to perform LVS. """
    debug.info(1, f"Running netgen for cell {cell_name}")
    from globals import OPTS
    work_dir = os.path.dirname(layout_spice)

    netgen_rc = os.environ.get("NETGEN_RC", "")
    if not os.path.exists(netgen_rc):
        netgen_rc = "nosetup"

    setup_script = os.path.join(work_dir, f"setup_lvs.sh")
    report_file = os.path.join(work_dir, f"{cell_name}.lvs.report")

    kwargs = {
        "netgen_exe": OPTS.lvs_exe[1],
        "setup_file": netgen_rc,
        "source_spice": source_spice,
        "layout_spice": layout_spice,
        "cell_name_": cell_name,
        "lvs_cell_name": lvs_cell_name,
        "report_file": report_file
    }

    with open(setup_script, "w") as f:
        f.write(netgen_template.format(**kwargs))
    os.system("chmod +x {}".format(setup_script))

    return_code, out_file, err_file = run_script(None, cell_name, "lvs",
                                                 command_template=setup_script)

    check_process_errors(err_file, "LVS", benign_errors=['property "area_ox"'])
    return return_code, out_file, report_file


def run_lvs(cell_name, gds_name, sp_name, final_verification=False):
    """Run LVS check on a given top-level name which is
    implemented in gds_name and sp_name. Final verification will
    ensure that there are no remaining virtual conections. """
    from globals import OPTS

    flatten = getattr(OPTS, "flat_lvs", True)

    mag_file = os.path.join(OPTS.openram_temp, f"{cell_name}.mag")
    if not os.path.exists(mag_file) or os.path.getmtime(mag_file) < os.path.getmtime(gds_name):
        run_script(generate_magic_script(gds_name, cell_name, True,
                                         "export", **{"other_commands": "writeall force\n"}),
                   cell_name=cell_name, op_name="export")

    generate_lvs_spice(mag_file, sp_name, final_verification, flatten)

    gen_layout_spice = os.path.join(OPTS.openram_temp, f"{cell_name}.spice")
    # to prevent overwrites during pex
    layout_spice = os.path.join(OPTS.openram_temp, f"{cell_name}.lvs.spice")
    shutil.copy2(gen_layout_spice, layout_spice)

    if os.path.getmtime(layout_spice) < os.path.getmtime(gds_name):
        debug.error("Modification time of layout spice should be > than gds."
                    " Error generating spice?")

    lvs_cell_name = cell_name + "_flat" * flatten

    return_code, out_file, report_file = run_netgen(cell_name, lvs_cell_name, layout_spice, sp_name)
    with open(report_file, "r") as f:
        results = f.read()

    total_errors = 0

    if "has no elements and/or nodes.  Not checked" in results:
        debug.warning("No transistor present in layout so no check")

    # Get property errors
    split = results.split("There were property errors.")
    if len(split) > 1:
        property_errors = split[1].split("Subcircuit pins:")[0].strip()
        num_prop_errors = property_errors.count("vs.")
        if num_prop_errors > 0:
            debug.info(1, f"{num_prop_errors} Property errors\n%s", property_errors)
        total_errors += num_prop_errors

    # Netlists match uniquely.
    # For hierarchical lvs, only consider the most recent message between match uniquely and do not match
    # so reverse the string to determine
    mismatch = False
    for line in reversed(results.split("\n")):
        if "Netlists match uniquely." in line:
            break
        elif "Netlists do not match." in line:
            mismatch = True
            break

    if mismatch:
        total_errors += 1

    if total_errors > 0:
        # Just print out the whole file, it is short.
        debug.info(1, results)
        # debug.error("LVS mismatch (results in {})".format(report_file))
    else:
        debug.info(1, "No LVS Error")

    return total_errors


def run_pex(cell_name, gds_name, sp_name, output=None,
            run_drc_lvs=True, correct_port_order=True, port_spice_file=None):
    """Run pex on a given top-level name which is
       implemented in gds_name and sp_name. """
    from globals import OPTS
    work_dir = OPTS.openram_temp

    port_spice_file = port_spice_file or sp_name

    if output is None:
        output = os.path.join(work_dir, f"{cell_name}.pex.spice")

    lvs_report = os.path.join(work_dir, f"{cell_name}.lvs.report")

    mag_file = os.path.join(OPTS.openram_temp, f"{cell_name}.mag")

    if run_drc_lvs or not os.path.exists(mag_file) or not os.path.exists(lvs_report):
        debug.info(1, "Forcing DRC + LVS runs before PEX")
        run_drc(cell_name, gds_name)
        run_lvs(cell_name, gds_name, sp_name)

    debug.info(1, "Run PEX for {}".format(cell_name))
    kwargs = get_lvs_kwargs(cell_name, mag_file, sp_name, flatten=True, final_verification=True)
    kwargs["output_file"] = output
    extract_script = generate_magic_script(mag_file, cell_name, flatten=False,
                                           op_name="pex",
                                           template=pex_template, **kwargs)
    return_code, out_file, err_file = run_script(extract_script, cell_name, "pex")
    benign_errors = ["smaller than extract section allows", "Couldn't find label"]
    check_process_errors(err_file, "pex", benign_errors=benign_errors)
    debug.info(1, f"Generated pex spice {output}")
    from verify.calibre import correct_port
    # TODO confirm large number of pins
    subckt_end_regex = re.compile(r"^[XRCM]+", re.MULTILINE)
    correct_port(cell_name, output, port_spice_file, subckt_end_regex=subckt_end_regex)
    remove_transistors_unit_suffix(output)
    return 0


def remove_transistors_unit_suffix(extracted_pex):
    """Remove unit suffix from transistor parameters suffix"""
    from base.spice_parser import SUFFIXES
    with open(extracted_pex, 'r') as f:
        lines = f.readlines()

    regex = re.compile(rf"((\S+)=([0-9e+\-.]+)([{''.join(SUFFIXES.keys())}]+))")
    with open(extracted_pex, "w") as f:
        for line in lines:
            if line.startswith("X"):
                for match in regex.findall(line):
                    numeric_val = float(match[2]) * SUFFIXES[match[3]]
                    line = line.replace(match[0], f"{match[1]}={numeric_val:.8g}")
            f.write(line)
