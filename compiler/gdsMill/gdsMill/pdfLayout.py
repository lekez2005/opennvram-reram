import random

import numpy as np
import pyx

FILL = "fill"
OUTLINE = "outline"
STRIPE = "stripe"
DASHED = "dashed"

class pdfLayout:
    """Class representing a view for a layout as a PDF"""
    def __init__(self,theLayout):
        self.canvas = pyx.canvas.canvas()
        self.layout = theLayout
        self.layerColors=dict()
        self.stripe_patterns = {}
        self.scale = 1.0
        self.transparency = 0.5
    
    def setScale(self,newScale):
        self.scale = float(newScale)
    
    def hexToRgb(self,hexColor):
        """
        Takes a hexadecimal color string i.e. "#219E1C" and converts it to an rgb float triplet ranging 0->1
        """
        red = int(hexColor[1:3],16)
        green = int(hexColor[3:5],16)
        blue = int(hexColor[5:7],16)        
        return (float(red)/255,float(green)/255,float(blue)/255)
    
    def randomHexColor(self):
        """
        Generates a random color in hex using the format #ABC123
        """
        red = hex(random.randint(0,255)).lstrip("0x")
        green = hex(random.randint(0,255)).lstrip("0x")
        blue = hex(random.randint(0,255)).lstrip("0x")
        return "#"+red+green+blue

    def transform_coordinates(self, uv_coordinates, origin, u_vector, v_vector):
        """
        This helper method will convert coordinates from a UV space to the cartesian XY space
        """
        xy_coordinates = []
        # setup a translation matrix
        t_matrix = np.array([[1.0, 0.0, origin[0]], [0.0, 1.0, origin[1]], [0.0, 0.0, 1.0]])
        # and a rotation matrix
        r_matrix = np.array([[u_vector[0], v_vector[0], 0.0], [u_vector[1], v_vector[1], 0.0],
                             [0.0, 0.0, 1.0]])
        for coordinate in uv_coordinates:
            # grab the point in UV space
            uv_point = np.array([coordinate[0], coordinate[1], 1.0]).reshape((3, 1))
            # now rotate and translate it back to XY space
            xy_point = np.matmul(r_matrix, uv_point)
            xy_point = np.matmul(t_matrix, xy_point).reshape(3)
            xy_coordinates += [(xy_point[0] / self.scale, xy_point[1] / self.scale)]
        return xy_coordinates

    @staticmethod
    def is_rect(coordinates):
        if not len(coordinates) == 5:
            return False
        return (
                coordinates[1][1] == coordinates[0][1] and
                coordinates[2][0] == coordinates[1][0] and
                coordinates[3][1] == coordinates[2][1] and
                coordinates[4][0] == coordinates[3][0] and
                coordinates[0] == coordinates[4]
        )

    def get_boundary_style(self, boundary):

        styles = [pyx.style.linewidth.THick]
        if boundary.drawingLayer in self.layerColors:
            style_def = self.layerColors[boundary.drawingLayer]
            color, style = style_def[:2]
            if len(self.layerColors[boundary.drawingLayer]) > 2:
                transparency = style_def[2]
            else:
                transparency = self.transparency
            layer_color = self.hexToRgb(color)
            layer_color = pyx.color.rgb(layer_color[0], layer_color[1], layer_color[2])

            if style == FILL:
                styles.append(pyx.deco.filled([layer_color]))
            elif style == DASHED:
                styles.append(pyx.style.linestyle.dashed)
            elif style == STRIPE:
                if color not in self.stripe_patterns:
                    pattern = pyx.pattern.pattern(attrs=[pyx.style.linewidth.THick])
                    pattern.stroke(pyx.path.line(0, 0, 0.25, 0.25), [layer_color])
                    self.stripe_patterns[color] = pattern
                styles.append(pyx.deco.filled([self.stripe_patterns[color]]))

            styles.extend([layer_color, pyx.color.transparency(transparency)])
        return styles

    def draw_path(self, coordinates, boundary):
        x = (coordinates[0][0])
        y = (coordinates[0][1])
        # method to draw a boundary with an XY offset
        shape = pyx.path.path(pyx.path.moveto(x, y))
        for index in range(1, len(coordinates)):
            x = coordinates[index][0]
            y = coordinates[index][1]
            shape.append(pyx.path.lineto(x, y))
        styles = self.get_boundary_style(boundary)
        self.canvas.stroke(shape, styles)

    def draw_rect(self, coordinates, boundary):
        width = coordinates[1][0] - coordinates[0][0]
        height = coordinates[3][1] - coordinates[0][1]
        styles = self.get_boundary_style(boundary)
        rect = pyx.path.rect(coordinates[0][0], coordinates[0][1], width, height)
        self.canvas.stroke(rect, styles)

    def draw_obj(self, obj, element):
        origin, u_vector, v_vector = element[1],element[2], element[3]
        coordinates = self.transform_coordinates(obj.coordinates, origin, u_vector, v_vector)
        if self.is_rect(coordinates):
            self.draw_rect(coordinates, obj)
        else:
            self.draw_path(coordinates, obj)

    def drawLayout(self):
        #use the layout xyTree and structureList
        #to draw ONLY the geometry in each structure
        #SREFS and AREFS are handled in the tree
        for element in self.layout.xyTree:
            #each element is (name,offsetTuple,rotate)
            structureToDraw = self.layout.structures[element[0]]
            for obj in structureToDraw.boundaries + structureToDraw.paths:
                self.draw_obj(obj, element)
        
    def writeToFile(self,filename):
        self.canvas.writePDFfile(filename)

    def writeSvgFile(self, filename):
        self.canvas.writeSVGfile(filename)
