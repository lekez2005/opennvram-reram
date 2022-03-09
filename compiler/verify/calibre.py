"""
This is a DRC/LVS interface for calibre. It implements completely
independently two functions: run_drc and run_lvs, that perform these
functions in batch mode and will return true/false if the result
passes. All of the setup (the rules, temp dirs, etc.) should be
contained in this file.  Replacing with another DRC/LVS tool involves
rewriting this code to work properly. Porting to a new technology in
Calibre means pointing the code to the proper DRC and LVS rule files.

A calibre DRC runset file contains, at the minimum, the following information:

*drcRulesFile: /mada/software/techfiles/FreePDK45/ncsu_basekit/techfile/calibre/calibreDRC.rul
*drcRunDir: .
*drcLayoutPaths: ./cell_6t.gds
*drcLayoutPrimary: cell_6t
*drcLayoutSystem: GDSII
*drcResultsformat: ASCII
*drcResultsFile: cell_6t.drc.results
*drcSummaryFile: cell_6t.drc.summary
*cmnFDILayerMapFile: ./layer.map
*cmnFDIUseLayerMap: 1

This can be executed in "batch" mode with the following command:

calibre -gui -drc example_drc_runset  -batch

To open the results, you can do this:

calibredrv cell_6t.gds
Select Verification->Start RVE.
Select the cell_6t.drc.results file.
Click on the errors and they will highlight in the design layout viewer.

For LVS:

*lvsRulesFile: /mada/software/techfiles/FreePDK45/ncsu_basekit/techfile/calibre/calibreLVS.rul
*lvsRunDir: .
*lvsLayoutPaths: ./cell_6t.gds
*lvsLayoutPrimary: cell_6t
*lvsSourcePath: ./cell_6t.sp
*lvsSourcePrimary: cell_6t
*lvsSourceSystem: SPICE
*lvsSpiceFile: extracted.sp
*lvsPowerNames: vdd 
*lvsGroundNames: vss
*lvsIgnorePorts: 1
*lvsERCDatabase: cell_6t.erc.results
*lvsERCSummaryFile: cell_6t.erc.summary
*lvsReportFile: cell_6t.lvs.report
*lvsMaskDBFile: cell_6t.maskdb
*cmnFDILayerMapFile: ./layer.map
*cmnFDIUseLayerMap: 1

To run and see results:

calibre -gui -lvs example_lvs_runset -batch
more cell_6t.lvs.report
"""


import os
import re

import debug
from base import utils
from base.utils import get_temp_file
from globals import OPTS
import tech
from tech import drc


def run_drc(cell_name, gds_name, exception_group=""):
    """Run DRC check on a given top-level name which is
       implemented in gds_name."""
    bail = 2
    if bail == 1:
        utils.to_cadence(gds_name)
        debug.check(False, "quick fail")
    elif bail == 2:
        utils.to_cadence(gds_name)
    elif bail == 3:
        return

    # the runset file contains all the options to run calibre
    debug.info(1, "Run DRC for {}".format(cell_name))
    drc_rules = drc["drc_rules"]

    rule_unselect = []
    group_unselect = []
    if "exceptions" in drc:
        drc_exceptions = drc["exceptions"]
        if "groups" in drc_exceptions:
            group_unselect.extend(drc_exceptions["groups"])
        if "all" in drc_exceptions:
            rule_unselect.extend(drc_exceptions["all"])
        if exception_group and exception_group in drc_exceptions:
            rule_unselect.extend(drc_exceptions[exception_group])

    rule_unselect_str = ""
    for i in range(0, len(rule_unselect)):
        rule_unselect_str += " {{check_unselect[{0}]}} {1}".format(i+1, rule_unselect[i])
    group_unselect_str = ""
    for i in range(0, len(group_unselect)):
        group_unselect_str += " {{group_unselect[{0}]}} {1}".format(i+1, group_unselect[i])


    drc_runset = {
        'drcRulesFile': drc_rules,
        'drcRunDir': OPTS.openram_temp,
        'drcLayoutPaths': gds_name,
        'drcLayoutPrimary': cell_name,
        'drcLayoutSystem': 'GDSII',
        'drcResultsformat': 'ASCII',
        'drcActiveRecipe': 'All checks (Modified)',
        'drcUserRecipes': '{{All checks (Modified)} {{group_unselect[1]} all {group_select[1]} rule_file ' +
            group_unselect_str + rule_unselect_str + '}}',
        'drcResultsFile': get_temp_file(cell_name + ".drc.results"),
        'drcSummaryFile': get_temp_file(cell_name + ".drc.summary"),
        'cmnFDILayerMapFile': drc["layer_map"],
        'cmnFDIUseLayerMap': 1
    }

    # write the runset file
    f = open(get_temp_file("drc_runset"), "w")
    for k in sorted(drc_runset.keys()):
        f.write("*{0}: {1}\n".format(k, drc_runset[k]))
    f.close()

    # run drc
    errfile = get_temp_file("{0}.drc.err".format(cell_name))
    outfile = get_temp_file("{0}.drc.out".format(cell_name))

    if os.path.exists(drc_runset['drcSummaryFile']):
        os.remove(drc_runset['drcSummaryFile'])

    cmd = "{0} -gui -drc {1} -batch".format(OPTS.drc_exe[1], get_temp_file("drc_runset"))
    debug.info(2, cmd)
    utils.run_command(cmd, outfile, errfile, verbose_level=3, cwd=OPTS.openram_temp)


    # check the result for these lines in the summary:
    # TOTAL Original Layer Geometries: 106 (157)
    # TOTAL DRC RuleChecks Executed:   156
    # TOTAL DRC Results Generated:     0 (0)
    try:
        f = open(drc_runset['drcSummaryFile'], "r")
    except:
        debug.error("Unable to retrieve DRC results file. Is calibre set up?",1)
    results = f.readlines()
    f.close()
    # those lines should be the last 3
    summary = []
    if results[-1].startswith("TOTAL DFM RDB Results Generated"): #28nm DRC also includes DFM results
        summary=results[-4:-1]
    else:
        summary = results[-3:]
    geometries = int(re.split(r"\W+", summary[0])[5])
    rulechecks = int(re.split(r"\W+", summary[1])[4])
    errors = int(re.split(r"\W+", summary[2])[5])

    # always display this summary 
    if errors > 0:        
        violations = [] # DRC violations
        in_statistics = False
        for i in range(len(results)-1, -1, -1): # iterate in reverse order for efficiency
            result = results[i]
            if result.startswith("--- RULECHECK"):
                in_statistics = False
                break
            if in_statistics:
                violations.append(result)
            if result.startswith("--- SUMMARY"):
                in_statistics = True
        violations.reverse()
        debug.error("{0}\tGeometries: {1}\tChecks: {2}\tErrors: {3} \n {4}".format(cell_name, 
                                                                            geometries,
                                                                            rulechecks,
                                                                            errors, 
                                                                            "".join(violations)))
    else:
        debug.info(1, "{0}\tGeometries: {1}\tChecks: {2}\tErrors: {3}".format(cell_name, 
                                                                              geometries,
                                                                              rulechecks,
                                                                              errors))
    return errors


def get_lvs_box_cells():
    if hasattr(tech, 'lvs_box_cells'):
        box_str_list = ['{{1 {}}}'.format(cell_name) for cell_name in tech.lvs_box_cells]
        return {
            #'lvsIncludeCmdsType': 'SVRF',
            #'lvsSVRFCmds': '{LVS PRESERVE BOX CELLS YES}',
            'cmnConfigureLVSBox': '1',
            'cmnLVSBoxes':        ' '.join(box_str_list),
        }
    return {}


def run_lvs(cell_name, gds_name, sp_name, final_verification=False):
    """Run LVS check on a given top-level name which is
    implemented in gds_name and sp_name. Final verification will
    ensure that there are no remaining virtual conections. """
    debug.info(1, "Run LVS for {}".format(cell_name))

    from tech import drc
    lvs_rules = drc["lvs_rules"]
    lvs_runset = {
        'lvsRulesFile': lvs_rules,
        'lvsRunDir': OPTS.openram_temp,
        'lvsLayoutPaths': gds_name,
        'lvsLayoutPrimary': cell_name,
        'lvsSourcePath': sp_name,
        'lvsSourcePrimary': cell_name,
        'lvsSourceSystem': 'SPICE',
        'lvsSpiceFile': get_temp_file("extracted.sp"),
        'lvsPowerNames': 'vdd',
        'lvsGroundNames': 'gnd',
        'lvsIncludeSVRFCmds': 1,
        'lvsIgnorePorts': 1,
        'lvsERCDatabase': get_temp_file(cell_name + ".erc.results"),
        'lvsERCSummaryFile': get_temp_file(cell_name + ".erc.summary"),
        'lvsReportFile': get_temp_file(cell_name + ".lvs.report"),
        'lvsMaskDBFile': get_temp_file(cell_name + ".maskdb"),
        'cmnFDILayerMapFile': drc["layer_map"],
        'cmnFDIUseLayerMap': 1,
        # TODO NONE vs SIMPLE vs ALL? None -> Simple change fixes an LVS error
        'lvsRecognizeGates': 'SIMPLE'
        #'cmnVConnectNamesState' : 'ALL', #connects all nets with the same name
    }
    lvs_runset.update(get_lvs_box_cells())

    # This should be removed for final verification
    if not final_verification:
        lvs_runset['cmnVConnectReport']=1
        lvs_runset['cmnVConnectNamesState']='ALL'



    # write the runset file
    f = open(get_temp_file("lvs_runset"), "w")
    for k in sorted(lvs_runset.keys()):
        f.write("*{0}: {1}\n".format(k, lvs_runset[k]))
    f.close()

    # run LVS
    errfile = get_temp_file("{}.err".format(cell_name))
    outfile = get_temp_file("{}.out".format(cell_name))

    cmd = "{0} -gui -lvs {1} -batch".format(OPTS.lvs_exe[1], get_temp_file("lvs_runset"))
    debug.info(2, cmd)
    utils.run_command(cmd, outfile, errfile, verbose_level=3, cwd=OPTS.openram_temp)

    summary_errors = get_lvs_summary_errors(lvs_runset['lvsReportFile'])

    # also check the extraction summary file
    f = open(lvs_runset['lvsReportFile'] + ".ext", "r")
    results = f.readlines()
    f.close()

    test = re.compile("ERROR:")
    exterrors = list(filter(test.search, results))
    for e in exterrors:
        debug.error(e.strip("\n"))

    test = re.compile("WARNING:")
    extwarnings = list(filter(test.search, results))
    for e in extwarnings:
        debug.warning(e.strip("\n"))

    # MRG - 9/26/17 - Change this to exclude warnings because of
    # multiple labels on different pins in column mux.
    ext_errors = len(exterrors)
    ext_warnings = len(extwarnings) 

    # also check the output file
    f = open(outfile, "r")
    results = f.readlines()
    f.close()

    # Errors begin with "ERROR:"
    test = re.compile("ERROR:")
    stdouterrors = list(filter(test.search, results))
    for e in stdouterrors:
        debug.error(e.strip("\n"))

    out_errors = len(stdouterrors)

    total_errors = summary_errors + out_errors + ext_errors
    return total_errors


def get_lvs_summary_errors(report_file):
    # check the result for these lines in the summary:
    f = open(report_file, "r")
    results = f.readlines()
    f.close()

    # NOT COMPARED
    # CORRECT
    # INCORRECT
    test = re.compile("#     CORRECT     #")
    correct = list(filter(test.search, results))
    test = re.compile("NOT COMPARED")
    notcompared = list(filter(test.search, results))
    test = re.compile("#     INCORRECT     #")
    incorrect = list(filter(test.search, results))

    # Errors begin with "Error:"
    test = re.compile(r"\s+Error:")
    errors = list(filter(test.search, results))
    for e in errors:
        debug.error(e.strip("\n"))

    summary_errors = len(notcompared) + len(incorrect) + len(errors)
    return summary_errors


def run_pex(cell_name, gds_name, sp_name, output=None, run_drc_lvs=True, correct_port_order=True):
    """Run pex on a given top-level name which is
       implemented in gds_name and sp_name. """

    from tech import drc
    if output == None:
        output = get_temp_file(cell_name + ".pex.netlist")

    # check if lvs report has been done
    # if not run drc and lvs
    if run_drc_lvs and not os.path.isfile(get_temp_file(cell_name + ".lvs.report")):
        run_drc(cell_name, gds_name)
        run_lvs(cell_name, gds_name, sp_name)

    debug.info(1, "Run PEX for {}".format(cell_name))

    pex_rules = drc["xrc_rules"]
    pex_runset = {
        'pexRulesFile': pex_rules,
        'pexRunDir': OPTS.openram_temp,
        'pexLayoutPaths': gds_name,
        'pexLayoutPrimary': cell_name,
        #'pexSourcePath' : OPTS.openram_temp+"extracted.sp",
        'pexSourcePath': sp_name,
        'pexSourcePrimary': cell_name,
        'pexReportFile': cell_name + ".lvs.report",
        'pexPexNetlistFile': output,
        'pexPexReportFile': cell_name + ".pex.report",
        'pexMaskDBFile': cell_name + ".maskdb",
        'cmnFDIDEFLayoutPath': cell_name + ".def",
        'cmnRunMT': "1",
        'cmnNumTurbo': "16",
        'pexPowerNames': "vdd",
        'pexGroundNames': "gnd",
        'pexPexGroundName': "1",
        'pexPexGroundNameValue': "gnd",
        'pexPexSeparator': "1",
        'pexPexSeparatorValue': "_",
        'pexPexNetlistNameSource': 'SOURCENAMES',
        'pexSVRFCmds': '{LVS PRESERVE BOX CELLS YES} {SOURCE CASE YES} {LAYOUT CASE YES}',
        'pexIncludeCmdsType': 'SVRF',  # used for preserving lvs box names
    }
    pex_runset.update(get_lvs_box_cells())

    # write the runset file
    f = open(get_temp_file("pex_runset"), "w")
    for k in sorted(pex_runset.keys()):
        f.write("*{0}: {1}\n".format(k, pex_runset[k]))
    f.close()

    # run pex
    errfile = get_temp_file("{}.pex.err".format(cell_name))
    outfile = get_temp_file("{}.pex.out".format(cell_name))

    cmd = "{0} -gui -pex {1} -batch ".format(OPTS.pex_exe[1],
                                                       get_temp_file("pex_runset"))
    debug.info(2, cmd)
    utils.run_command(cmd, outfile, errfile, verbose_level=3, cwd=OPTS.openram_temp)

    summary_errors = get_lvs_summary_errors(get_temp_file(cell_name + ".lvs.report"))
    if summary_errors > 0:
        debug.error("LVS errors during PEX: {}".format(summary_errors))

    # also check the output file
    f = open(outfile, "r")
    results = f.readlines()
    f.close()

    # Errors begin with "ERROR:"
    test = re.compile("ERROR:")
    stdouterrors = list(filter(test.search, results))
    for e in stdouterrors:
        debug.error(e.strip("\n"))

    out_errors = len(stdouterrors)

    assert(os.path.isfile(output))
    if correct_port_order:
        correct_port(cell_name, output, sp_name)

    return out_errors


def correct_port(name, output_file_name, ref_file_name, subckt_end_regex=None):
    if subckt_end_regex is None:
        subckt_end_regex = re.compile(r"\* \n")
    pex_file = open(output_file_name, "r")
    contents = pex_file.read()
    # locate the start of circuit definition line
    match = re.search(".subckt " + str(name) + ".*", contents, re.IGNORECASE)
    match_index_start = match.start()
    pex_file.seek(match_index_start)
    rest_text = pex_file.read()
    # locate the end of circuit definition line
    match = re.search(subckt_end_regex, rest_text)
    match_index_end = match.start()
    # store the unchanged part of pex file in memory
    pex_file.seek(0)
    part1 = pex_file.read(match_index_start)
    pex_file.seek(match_index_start + match_index_end)
    part2 = pex_file.read()
    pex_file.close()

    # obtain the correct definition line from the original spice file
    sp_file = open(ref_file_name, "r")
    contents = sp_file.read()
    circuit_title = re.search(".SUBCKT " + str(name) + ".*\n", contents)
    circuit_title = circuit_title.group()
    sp_file.close()

    # write the new pex file with info in the memory
    output_file = open(output_file_name, "w")
    output_file.write(part1)
    output_file.write(circuit_title)
    output_file.write(part2)
    output_file.close()
