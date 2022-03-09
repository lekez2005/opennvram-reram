from testutils import OpenRamTest


class LayoutClearancesTest(OpenRamTest):
    def make_design(self, dimensions=None):
        from base.design import design

        dimensions = dimensions or [1.0, 0.9]

        class CustomDesign(design):
            name = "clearance_test"

            def __init__(self):
                if self.name in design.name_map:
                    del design.name_map[self.name]
                design.__init__(self, self.name)
                self.width, self.height = dimensions

        return CustomDesign()

    @staticmethod
    def evaluate(mod, layer, horz=True, *args, **kwargs):
        from base.layout_clearances import find_clearances, HORIZONTAL, VERTICAL
        if isinstance(layer, int):
            layer = f"metal{layer}"
        direction = HORIZONTAL if horz else VERTICAL
        return find_clearances(mod, layer, direction, *args, **kwargs)

    def test_range_overlap(self):
        """Test range overlap detection"""
        from base.layout_clearances import get_range_overlap
        self.assertTrue(get_range_overlap((0, 1), (0.5, 1)))
        self.assertFalse(get_range_overlap((0, 1), (1.1, 1.3)))
        self.assertTrue(get_range_overlap((1, 0), (0.2, 0.3)))

    def test_empty_layout(self):
        """Empty layout should return full width"""
        mod = self.make_design()
        clearances = self.evaluate(mod, 1)
        self.assertEqual(len(clearances), 1, "One clearance should be detected")
        self.assertEqual(clearances[0][0], 0, "Left edge should be 0")
        self.assertEqual(clearances[0][1], mod.width, "Right edge should be width")

    def create_one_blockage(self):
        from base.design import METAL1
        from base.utils import round_to_grid
        from base.vector import vector
        mod = self.make_design()
        x_offset = 0.5 * mod.width - 0.5 * mod.m1_width
        rect = mod.add_rect(METAL1, vector(x_offset, 0))
        edges = (round_to_grid(rect.lx()), round_to_grid(rect.rx()))
        return mod, rect, edges

    def test_one_blockage(self):
        """One blockage should produce two spaces"""
        mod, rect, edges = self.create_one_blockage()
        clearances = self.evaluate(mod, 1)
        self.assertEqual(len(clearances), 2, "Two clearances should be detected")
        self.assertEqual(clearances[0], (0, edges[0]), "Left clearance")
        self.assertEqual(clearances[1], (edges[1], mod.width), "Right clearance")

    def test_blockage_outside_range(self):
        """Entire width should be returned if blockage is outside y range"""
        mod, rect, edges = self.create_one_blockage()
        # test outside range
        clearances = self.evaluate(mod, 1, region=(rect.uy() + 0.1, mod.height))
        self.assertEqual(clearances, [(0, mod.width)])

    def test_blockage_at_edge(self):
        """If blockage is at the edge, then only one clearance should be detected"""
        from base.design import METAL1
        from base.utils import round_to_grid
        from base.vector import vector
        mod = self.make_design()
        x_offset = -0.5 * mod.m1_width
        rect = mod.add_rect(METAL1, vector(x_offset, 0))
        clearances = self.evaluate(mod, 1)
        self.assertEqual(len(clearances), 1, "One clearance should be detected")
        self.assertEqual(clearances[0], (round_to_grid(rect.rx()),
                                         round_to_grid(mod.width)), "Clearance range")

    def test_blockage_overlap(self):
        """If blockages overlap, clearances should be consolidated"""
        from base.design import METAL1
        from base.utils import round_to_grid
        from base.vector import vector

        mod = self.make_design()
        x_offset = 0.5 * mod.width - 0.5 * mod.m1_width
        rect_1 = mod.add_rect(METAL1, vector(x_offset, 0))
        rect_2 = mod.add_rect(METAL1, vector(rect_1.rx(), 0))

        clearances = self.evaluate(mod, 1)

        edges_1 = (round_to_grid(rect_1.lx()), round_to_grid(rect_1.rx()))
        edges_2 = (round_to_grid(rect_2.lx()), round_to_grid(rect_2.rx()))

        self.assertEqual(len(clearances), 2, "Two clearances should be detected")
        self.assertEqual(clearances[0], (0, edges_1[0]), "Left clearance")
        self.assertEqual(clearances[1], (edges_2[1], mod.width), "Right clearance")


OpenRamTest.run_tests(__name__)
