#!/usr/bin/env python3
"Run a regression test on a basic path"

from testutils import OpenRamTest
import globals
from globals import OPTS


class PathTest(OpenRamTest):

    def runTest(self):
        import tech

        from base import design
        from base import path

        min_space = 2 * tech.drc["minwidth_metal1"]
        layer_stack = ("metal1")
        # checks if we can retrace a path
        position_list = [[0,0],
                         [0, 3 * min_space ],
                         [4 * min_space, 3 * min_space ],
                         [4 * min_space, 3 * min_space ],
                         [0, 3 * min_space ],
                         [0, 6 * min_space ]]
        w = design.design("path_test0")
        path.path(w,layer_stack, position_list)
        self.local_drc_check(w)

        min_space = 2 * tech.drc["minwidth_metal1"]
        layer_stack = ("metal1")
        old_position_list = [[0, 0],
                             [0, 3 * min_space],
                             [1 * min_space, 3 * min_space],
                             [4 * min_space, 3 * min_space],
                             [4 * min_space, 0],
                             [7 * min_space, 0],
                             [7 * min_space, 4 * min_space],
                             [-1 * min_space, 4 * min_space],
                             [-1 * min_space, 0]]
        position_list  = [[x+min_space, y+min_space] for x,y in old_position_list]
        w = design.design("path_test1")
        path.path(w,layer_stack, position_list)
        self.local_drc_check(w)

        min_space = 2 * tech.drc["minwidth_metal2"]
        layer_stack = ("metal2")
        old_position_list = [[0, 0],
                             [0, 3 * min_space],
                             [1 * min_space, 3 * min_space],
                             [4 * min_space, 3 * min_space],
                             [4 * min_space, 0],
                             [7 * min_space, 0],
                             [7 * min_space, 4 * min_space],
                             [-1 * min_space, 4 * min_space],
                             [-1 * min_space, 0]]
        position_list  = [[x-min_space, y-min_space] for x,y in old_position_list]
        w = design.design("path_test2")
        path.path(w, layer_stack, position_list)
        self.local_drc_check(w)

        min_space = 2 * tech.drc["minwidth_metal3"]
        layer_stack = ("metal3")
        position_list = [[0, 0],
                         [0, 3 * min_space],
                         [1 * min_space, 3 * min_space],
                         [4 * min_space, 3 * min_space],
                         [4 * min_space, 0],
                         [7 * min_space, 0],
                         [7 * min_space, 4 * min_space],
                         [-1 * min_space, 4 * min_space],
                         [-1 * min_space, 0]]
        # run on the reverse list
        position_list.reverse()
        w = design.design("path_test3")
        path.path(w, layer_stack, position_list)
        self.local_drc_check(w)

        # return it back to it's normal state
        OPTS.check_lvsdrc = True
        globals.end_openram()
        

OpenRamTest.run_tests(__name__)
