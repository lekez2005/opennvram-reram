import glob
import math
import os
import sys
import unittest
import inspect
from importlib import reload

module_dir = os.path.abspath(os.path.dirname(__file__))
sys.path.append(os.path.abspath(os.path.join(module_dir, "../")))

from globals import OPTS
import globals
import options


class OpenRamTest(unittest.TestCase):
    """ Base unit test that we have some shared classes in. """

    debug = None
    initialized = False
    config_template = "config_20_{}"
    temp_folder = None

    @staticmethod
    def run_tests(name):
        if name == "__main__":
            parse_args()
            unittest.main()

    @classmethod
    def initialize_tests(cls, config_template=None):
        if not config_template:
            config_template = cls.config_template
        parse_args()
        from globals import OPTS
        config_template = getattr(OPTS, "config_file", config_template)
        globals.init_openram(config_template.format(OPTS.tech_name), openram_temp=cls.temp_folder)
        if OPTS.debug_level > 0:
            header(inspect.getfile(cls), OPTS.tech_name)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import importlib
        OpenRamTest.debug = importlib.import_module('debug')
        OPTS.check_lvsdrc = False

    def run(self, result=None):
        if not self.initialized:
            self.initialize_tests()
            self.initialized = True
        super().run(result)


    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        globals.end_openram()

    def setUp(self):
        self.corner = (OPTS.process_corners[0], OPTS.supply_voltages[0], OPTS.temperatures[0])
        OPTS.check_lvsdrc = False
        self.reset()

    def temp_file(self, file_name):
        return os.path.join(OPTS.openram_temp, file_name)
    
    def local_drc_check(self, w):
        tempgds = os.path.join(OPTS.openram_temp, "temp.gds")
        w.gds_write(tempgds)
        import verify
        self.assertFalse(verify.run_drc(w.drc_gds_name, tempgds,
                                        exception_group=w.__class__.__name__))

        if OPTS.purge_temp:
            self.cleanup()  
    
    def local_check(self, a, final_verification=False):

        tempspice = os.path.join(OPTS.openram_temp, "temp.sp")
        tempgds = os.path.join(OPTS.openram_temp, "temp.gds")

        a.sp_write(tempspice)
        a.gds_write(tempgds)

        import verify
        try:
            self.assertTrue(verify.run_drc(a.drc_gds_name, tempgds,
                                           exception_group=a.__class__.__name__) == 0)
        except Exception as ex:
            self.reset()
            self.fail("DRC failed: {}".format(a.name))

            
        try:
            self.assertTrue(verify.run_lvs(a.name, tempgds, tempspice, final_verification)==0)
        except Exception as ex:
            self.reset()
            self.fail("LVS mismatch: {}".format(a.name))

        self.reset()
        if OPTS.purge_temp:
            self.cleanup()

    def cleanup(self):
        """ Reset the duplicate checker and cleanup files. """
        files = glob.glob(os.path.join(OPTS.openram_temp, '*'))
        for f in files:
            # Only remove the files
            if os.path.isfile(f):
                os.remove(f)        

    def reset(self):
        """ Reset the static duplicate name checker for unit tests """
        from base import design
        design.design.name_map=[]

    @staticmethod
    def load_class_from_opts(mod_name):
        config_mod_name = getattr(OPTS, mod_name)
        from base.design import design
        return design.import_mod_class_from_str(config_mod_name)

    @staticmethod
    def create_class_from_opts(opt_name, *args, **kwargs):
        from base.design import design
        from globals import OPTS
        opt_val = getattr(OPTS, opt_name)
        mod = design.create_mod_from_str_(opt_val, *args, **kwargs)
        return mod

    @staticmethod
    def get_words_per_row(num_cols, words_per_row, word_size=32):
        """Assumes 32 bit word size"""
        if words_per_row is not None:
            if isinstance(words_per_row, list):
                return words_per_row
            else:
                return [words_per_row]
        max_col_address_size = int(math.log(num_cols, 2) - math.log(word_size, 2))
        return [int(2 ** x) for x in range(max_col_address_size + 1)]

    def isclose(self, value1, value2, error_tolerance=1e-2):
        """ This is used to compare relative values. """
        import debug
        relative_diff = abs(value1 - value2) / max(value1,value2)
        check = relative_diff <= error_tolerance
        if not check:
            self.fail("NOT CLOSE {0} {1} relative diff={2}".format(value1,value2,relative_diff))
        else:
            debug.info(2,"CLOSE {0} {1} relative diff={2}".format(value1,value2,relative_diff))

    def relative_compare(self, value1,value2,error_tolerance):
        """ This is used to compare relative values. """
        if (value1==value2): # if we don't need a relative comparison!
            return True
        return (abs(value1 - value2) / max(value1,value2) <= error_tolerance)

    def isapproxdiff(self, f1, f2, error_tolerance=0.001):
        """Compare two files.

        Arguments:
        
        f1 -- First file name
        
        f2 -- Second file name

        Return value:
        
        True if the files are the same, False otherwise.
        
        """
        import re
        import debug

        with open(f1, 'rb') as fp1, open(f2, 'rb') as fp2:
            while True:
                b1 = fp1.readline()
                b2 = fp2.readline()
                #print "b1:",b1,
                #print "b2:",b2,

                # 1. Find all of the floats using a regex
                numeric_const_pattern = r"""
                [-+]? # optional sign
                (?:
                (?: \d* \. \d+ ) # .1 .12 .123 etc 9.1 etc 98.1 etc
                |
                (?: \d+ \.? ) # 1. 12. 123. etc 1 12 123 etc
                )
                # followed by optional exponent part if desired
                (?: [Ee] [+-]? \d+ ) ?
                """
                rx = re.compile(numeric_const_pattern, re.VERBOSE)
                b1_floats=rx.findall(b1)
                b2_floats=rx.findall(b2)
                debug.info(3,"b1_floats: "+str(b1_floats))
                debug.info(3,"b2_floats: "+str(b2_floats))
        
                # 2. Remove the floats from the string
                for f in b1_floats:
                    b1=b1.replace(str(f),"",1)
                for f in b2_floats:
                    b2=b2.replace(str(f),"",1)
                #print "b1:",b1,
                #print "b2:",b2,
            
                # 3. Check if remaining string matches
                if b1 != b2:
                    self.fail("MISMATCH Line: {0}\n!=\nLine: {1}".format(b1,b2))

                # 4. Now compare that the floats match
                if len(b1_floats)!=len(b2_floats):
                    self.fail("MISMATCH Length {0} != {1}".format(len(b1_floats),len(b2_floats)))
                for (f1,f2) in zip(b1_floats,b2_floats):
                    if not self.relative_compare(float(f1),float(f2),error_tolerance):
                        self.fail("MISMATCH Float {0} != {1}".format(f1,f2))

                if not b1 and not b2:
                    return



    def isdiff(self,file1,file2):
        """ This is used to compare two files and display the diff if they are different.. """
        import debug
        import filecmp
        import difflib
        check = filecmp.cmp(file1, file2)
        if not check:
            debug.info(2,"MISMATCH {0} {1}".format(file1,file2))
            f1 = open(file1,"r")
            s1 = f1.readlines()
            f2 = open(file2,"r")
            s2 = f2.readlines()
            for line in difflib.unified_diff(s1, s2):
                debug.info(3,line)
            self.fail("MISMATCH {0} {1}".format(file1,file2))
        else:
            debug.info(2,"MATCH {0} {1}".format(file1,file2))


def parse_args():
    if not OPTS.tech_name:  # args not previously parsed
        globals.parse_args()
        del sys.argv[1:]


def replace_custom_temp(suffix, config_module_name):
    config_module = __import__(config_module_name)

    temp_folder = options.options.openram_temp
    new_temp = os.path.join(temp_folder, suffix)

    config_module.openram_temp = new_temp

    for attr in ["spice_file", "pex_spice", "reduced_spice", "gds_file"]:
        default_val = getattr(options.options, attr)
        file_name = os.path.basename(default_val)
        new_val = os.path.join(new_temp, file_name)
        setattr(config_module, attr, new_val)


def header(filename, technology):
    import debug
    tst = "Running Test for:"
    debug.print_str("\n")
    debug.print_str(" ______________________________________________________________________________ ")
    debug.print_str("|==============================================================================|")
    debug.print_str("|=========" + tst.center(60) + "=========|")
    debug.print_str("|=========" + technology.center(60) + "=========|")
    debug.print_str("|=========" + filename.center(60) + "=========|")
    from globals import OPTS
    debug.print_str("|=========" + OPTS.openram_temp.center(60) + "=========|")
    debug.print_str("|==============================================================================|")
