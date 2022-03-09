#!/usr/bin/env python3
"Run a regression test on a basic wire"

from testutils import OpenRamTest


class WireTest(OpenRamTest):

    def runTest(self):
        from base import wire
        import tech
        from base import design

        if tech.info["horizontal_poly"]:

            min_space = 2 * (tech.drc["minwidth_poly"] +
                             tech.drc["minwidth_metal1"])
            layer_stack = ("poly", "contact", "metal1")
            old_position_list = [[0, 0],
                                 [0, 3 * min_space],
                                 [1 * min_space, 3 * min_space],
                                 [4 * min_space, 3 * min_space],
                                 [4 * min_space, 0],
                                 [7 * min_space, 0],
                                 [7 * min_space, 4 * min_space],
                                 [-1 * min_space, 4 * min_space],
                                 [-1 * min_space, 0]]
            position_list = [[x - min_space, y - min_space] for x, y in old_position_list]
            w = design.design("wire_test1")
            wire.wire(w, layer_stack, position_list)
            self.local_drc_check(w)

            min_space = 2 * (tech.drc["minwidth_poly"] +
                             tech.drc["minwidth_metal1"])
            layer_stack = ("metal1", "contact", "poly")
            old_position_list = [[0, 0],
                                 [0, 3 * min_space],
                                 [1 * min_space, 3 * min_space],
                                 [4 * min_space, 3 * min_space],
                                 [4 * min_space, 0],
                                 [7 * min_space, 0],
                                 [7 * min_space, 4 * min_space],
                                 [-1 * min_space, 4 * min_space],
                                 [-1 * min_space, 0]]
            position_list = [[x + min_space, y + min_space] for x, y in old_position_list]
            w = design.design("wire_test2")
            wire.wire(w, layer_stack, position_list)
            self.local_drc_check(w)

        min_space = 2 * (tech.drc["minwidth_metal2"] +
                         tech.drc["minwidth_metal1"])
        layer_stack = ("metal1", "via1", "metal2")
        position_list = [[0, 0],
                         [0, 3 * min_space],
                         [1 * min_space, 3 * min_space],
                         [4 * min_space, 3 * min_space],
                         [4 * min_space, 0],
                         [7 * min_space, 0],
                         [7 * min_space, 4 * min_space],
                         [-1 * min_space, 4 * min_space],
                         [-1 * min_space, 0]]
        w = design.design("wire_test3")
        wire.wire(w, layer_stack, position_list)
        self.local_drc_check(w)

        min_space = 2 * (tech.drc["minwidth_metal2"] +
                         tech.drc["minwidth_metal1"])
        layer_stack = ("metal2", "via1", "metal1")
        position_list = [[0, 0],
                         [0, 3 * min_space],
                         [1 * min_space, 3 * min_space],
                         [4 * min_space, 3 * min_space],
                         [4 * min_space, 0],
                         [7 * min_space, 0],
                         [7 * min_space, 4 * min_space],
                         [-1 * min_space, 4 * min_space],
                         [-1 * min_space, 0]]
        w = design.design("wire_test4")
        wire.wire(w, layer_stack, position_list)
        self.local_drc_check(w)

        min_space = 2 * (tech.drc["minwidth_metal2"] +
                         tech.drc["minwidth_metal3"])
        layer_stack = ("metal2", "via2", "metal3")
        position_list = [[0, 0],
                         [0, 3 * min_space],
                         [1 * min_space, 3 * min_space],
                         [4 * min_space, 3 * min_space],
                         [4 * min_space, 0],
                         [7 * min_space, 0],
                         [7 * min_space, 4 * min_space],
                         [-1 * min_space, 4 * min_space],
                         [-1 * min_space, 0]]
        position_list.reverse()
        w = design.design("wire_test5")
        wire.wire(w, layer_stack, position_list)
        self.local_drc_check(w)

        min_space = 2 * (tech.drc["minwidth_metal2"] +
                         tech.drc["minwidth_metal3"])
        layer_stack = ("metal3", "via2", "metal2")
        position_list = [[0, 0],
                         [0, 3 * min_space],
                         [1 * min_space, 3 * min_space],
                         [4 * min_space, 3 * min_space],
                         [4 * min_space, 0],
                         [7 * min_space, 0],
                         [7 * min_space, 4 * min_space],
                         [-1 * min_space, 4 * min_space],
                         [-1 * min_space, 0]]
        position_list.reverse()
        w = design.design("wire_test6")
        wire.wire(w, layer_stack, position_list)
        self.local_drc_check(w)


OpenRamTest.run_tests(__name__)
