from modules.sense_amp_array import sense_amp_array


class latched_sense_amp_array(sense_amp_array):

    def add_pins(self):
        for word in range(self.word_size):
            self.add_pin("bl[{0}]".format(word))
            self.add_pin("br[{0}]".format(word))
            self.add_pin("dout[{0}]".format(word))
            if "dout_bar" in self.child_mod.pins:
                self.add_pin("dout_bar[{0}]".format(word))

        self.add_pin("en")
        self.add_pin("sampleb")
        self.add_pin("vdd")
        self.add_pin("gnd")
