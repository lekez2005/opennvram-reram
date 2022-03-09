from reram_test_base import ReRamTestBase


class RowDecoderTest(ReRamTestBase):
    def test_2x4_predecoder(self):
        from modules.hierarchical_predecode2x4 import hierarchical_predecode2x4
        a = hierarchical_predecode2x4(route_top_rail=True, use_flops=True)
        self.local_check(a)

    def test_3x8_predecoder(self):
        from modules.hierarchical_predecode3x8 import hierarchical_predecode3x8
        a = hierarchical_predecode3x8(route_top_rail=True, use_flops=True)
        self.local_check(a)

    def test_row_decoder(self):
        cell = self.create_class_from_opts("decoder", rows=32)
        self.local_check(cell)


RowDecoderTest.run_tests(__name__)
