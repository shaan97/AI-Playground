"""Chunky extruded arcade-logo letters."""
import numpy as np

from . import font
from .engine import Sprite
from .palette import INK, WHITE


def logo_letter(ch, scale, grad, extrude, depth=5, hi=WHITE, outline=INK, ow=2):
    m = font.text_mask(ch, scale, spacing=0)
    h, w = m.shape
    H_, W_ = h + depth + 2 * ow, w + 2 * ow
    body = np.zeros((H_, W_), bool)
    rgb = np.zeros((H_, W_, 3), np.uint8)
    # extrusion (straight down), darker with depth
    for d in range(depth, 0, -1):
        sl = body[ow + d:ow + d + h, ow:ow + w]
        sl |= m
        col = extrude[min(len(extrude) - 1, (d - 1) * len(extrude) // depth)]
        rgb[ow + d:ow + d + h, ow:ow + w][m] = col
    body[ow:ow + h, ow:ow + w] |= m
    # outline around everything
    full = font.dilate(body, ow)[ow:ow + H_, ow:ow + W_]
    out_rgb = np.zeros((H_, W_, 3), np.uint8)
    out_rgb[full] = outline
    out_rgb[body] = rgb[body]
    # face fill: gradient in bands aligned to the font's pixel rows
    n = len(grad)
    rows = np.arange(h) // scale                       # 0..6
    band = np.clip(rows * n // font.GLYPH_H, 0, n - 1)
    face = np.array(grad, np.uint8)[band][:, None, :].repeat(w, axis=1)
    # highlight on top edge of every stroke
    up = np.zeros_like(m)
    up[1:] = m[:-1]
    top = m & ~up
    face[top] = hi
    # darker 1px lip on the bottom edge of strokes (before extrusion)
    dn = np.zeros_like(m)
    dn[:-1] = m[1:]
    bot = m & ~dn
    face[bot] = (np.array(grad[-1], np.float32) * 0.8).astype(np.uint8)
    out_rgb[ow:ow + h, ow:ow + w][m] = face[m]
    spr = Sprite(out_rgb, full)
    spr.face = np.zeros((H_, W_), bool)
    spr.face[ow:ow + h, ow:ow + w] = m
    return spr
