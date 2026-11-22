"""Read pixels back out of a Deep Zoom pyramid (the stitched wall's tiles).

The wall is far too wide to hold as one image (708,928 px at full size), so the places that
need to look at part of it read just the tiles that cover the stretch they want.
"""
import math
import os
import xml.etree.ElementTree as ET

import cv2
import numpy as np


class Pyramid:
    """A Deep Zoom image on disk: `<name>.dzi` beside a `<name>_files/<level>/<col>_<row>.<ext>` tree."""

    def __init__(self, dzi_path):
        root = ET.parse(dzi_path).getroot()
        ns = root.tag[:root.tag.index('}') + 1] if root.tag.startswith('{') else ''
        size = root.find(ns + 'Size')
        self.width, self.height = int(size.get('Width')), int(size.get('Height'))
        self.tile = int(root.get('TileSize'))
        self.overlap = int(root.get('Overlap', 0))
        self.ext = root.get('Format', 'jpg')
        self.files = os.path.splitext(dzi_path)[0] + '_files'
        self.max_level = math.ceil(math.log2(max(self.width, self.height)))

    def level_for(self, divisor):
        """The level that shows the image at 1/divisor of full size (a power of two)."""
        return self.max_level - int(round(math.log2(divisor)))

    def size_at(self, level):
        scale = 2.0 ** (level - self.max_level)
        return math.ceil(self.width * scale), math.ceil(self.height * scale)

    def read(self, level, x0, x1):
        """Columns [x0, x1) of one level, full height, as a BGR array. Missing tiles stay black."""
        width, height = self.size_at(level)
        x0, x1 = max(0, int(x0)), min(width, int(x1))
        out = np.zeros((height, max(0, x1 - x0), 3), np.uint8)
        if x1 <= x0:
            return out
        for col in range(x0 // self.tile, (x1 - 1) // self.tile + 1):
            for row in range(math.ceil(height / self.tile)):
                path = os.path.join(self.files, str(level), '%d_%d.%s' % (col, row, self.ext))
                tile = cv2.imread(path) if os.path.exists(path) else None
                if tile is None:
                    continue
                # tiles carry `overlap` extra pixels on each interior edge; keep just the tile's own square
                tile = tile[self.overlap if row else 0:, self.overlap if col else 0:][:self.tile, :self.tile]
                left, top = col * self.tile, row * self.tile
                a, b = max(left, x0), min(left + tile.shape[1], x1)
                rows = min(tile.shape[0], height - top)
                if b > a:
                    out[top:top + rows, a - x0:b - x0] = tile[:rows, a - left:b - left]
        return out
