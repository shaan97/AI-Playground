"""Set pieces: the Star Core, its tower, the alien UFO."""
import math

import numpy as np

from .engine import star_glint
from .palette import (AMBER, CYAN, GOLD, LEMON, LIME, MAGENTA, ORANGE, PINK, RED, ROSE, WHITE, YELLOW)
from .procgen import add_outline, bevel_shade, faceted_star, poly_mask, _quantize

STAR_LIGHT = [WHITE, LEMON, YELLOW, GOLD]
STAR_DARK = [YELLOW, GOLD, AMBER, ORANGE]


class StarCore:
    """The glowing, spinning star everyone is after."""

    def __init__(self, r=11):
        self.r = r
        self.frames = [faceted_star(r, (i / 24) * (2 * math.pi / 5), STAR_LIGHT, STAR_DARK) for i in range(24)]

    def draw(self, cv, x, y, t, scale=1.0, rays=True, glow=1.0):
        if rays and glow > 0:
            n = 10
            for i in range(n):
                a = t * 0.02 + i * math.tau / n
                ln = (22 + 6 * math.sin(t * 0.1 + i * 1.7)) * scale * glow
                x1, y1 = x + math.cos(a) * ln, y + math.sin(a) * ln
                col = LEMON if i % 2 == 0 else AMBER
                n_pts = int(ln)
                for k in range(4, n_pts, 1):
                    if (k + t // 2) % 3 == 0:
                        continue
                    cv.pset(x + (x1 - x) * k / n_pts, y + (y1 - y) * k / n_pts, col)
            rr = (15 + 2 * math.sin(t * 0.15)) * scale * glow
            if rr > 2:
                cv.ring(x, y, rr, (255, 220, 120), 1)
        if scale >= 0.99:
            spr = self.frames[(t // 2) % len(self.frames)]
        else:
            r = max(2, int(self.r * scale))
            spr = faceted_star(r, (t % 48) / 48 * (2 * math.pi / 5), STAR_LIGHT, STAR_DARK)
        cv.blit(spr, x - spr.w // 2, y - spr.h // 2)
        if (t // 6) % 4 == 0:
            star_glint(cv, x - 4 * scale, y - 5 * scale, 2, WHITE)


def draw_tower(cv, cx, base_y, top_y, t, lit=True):
    """A slim futuristic spire with a cradle on top (screen coords)."""
    h = base_y - top_y
    for y in range(int(top_y), int(base_y)):
        k = (y - top_y) / h
        half = int(3 + k * 16)
        cv.rect(cx - half, y, half * 2, 1, (30, 18, 58))
        cv.pset(cx - half, y, (70, 40, 110))
        cv.pset(cx + half - 1, y, (18, 10, 40))
        # window strip
        if y % 4 == 0 and k > 0.12:
            for wx in range(-half + 3, half - 3, 3):
                on = ((wx * 7 + y * 13) % 5) != 0
                if on:
                    cv.pset(cx + wx, y, (255, 200, 110) if lit and (wx + y) % 3 else (120, 220, 255) if lit else (60, 40, 80))
    # ring platforms
    for k, yy in enumerate((top_y + 26, top_y + 60, top_y + 100)):
        half = int(3 + ((yy - top_y) / h) * 16) + 6
        cv.rect(cx - half, yy, half * 2, 3, (56, 36, 96))
        cv.rect(cx - half, yy, half * 2, 1, (120, 80, 170))
        for i in range(-half + 2, half - 1, 4):
            cv.pset(cx + i, yy + 1, PINK if lit and (i // 4 + t // 10) % 2 else (90, 40, 90))
    # cradle
    cv.rect(cx - 9, top_y - 2, 18, 3, (70, 50, 120))
    cv.rect(cx - 9, top_y - 2, 18, 1, (150, 120, 200))
    cv.rect(cx - 10, top_y - 8, 2, 7, (70, 50, 120))
    cv.rect(cx + 8, top_y - 8, 2, 7, (70, 50, 120))
    if lit:
        cv.pset(cx - 9, top_y - 9, CYAN)
        cv.pset(cx + 9, top_y - 9, CYAN)


def build_ufo():
    w, h = 104, 44
    rgb = np.zeros((h, w, 3), np.uint8)
    mask = np.zeros((h, w), bool)
    hull = [WHITE, (226, 222, 250), (190, 186, 226), (150, 146, 196), (110, 104, 160), (74, 68, 120),
            (46, 40, 84)]
    lower = poly_mask(w, h, ellipses=[(24, 24, 80, 42)])
    rgb[lower] = bevel_shade(lower, [(150, 146, 196), (110, 104, 160), (74, 68, 120), (46, 40, 84),
                                     (30, 26, 60)])[lower]
    mask |= lower
    disc = poly_mask(w, h, ellipses=[(0, 14, 103, 34)])
    rgb[disc] = bevel_shade(disc, hull, grad=1.2)[disc]
    mask |= disc
    # dark rim band
    band = disc & poly_mask(w, h, rects=[(0, 24, 103, 26)])
    rgb[band] = (40, 30, 70)
    # glass dome (magenta/pink, with a highlight)
    dome = poly_mask(w, h, ellipses=[(32, 0, 71, 30)]) & poly_mask(w, h, rects=[(0, 0, w, 18)])
    yy, xx = np.nonzero(dome)
    lvl = np.zeros((h, w), np.float32)
    lvl[dome] = np.clip(((xx - 40) ** 2 + (yy - 5) ** 2) ** 0.5 / 22 * 4, 0, 4)
    dome_rgb = _quantize(lvl, [WHITE, ROSE, PINK, MAGENTA, (150, 40, 150)])
    rgb[dome] = dome_rgb[dome]
    mask |= dome
    # emitter
    emit = poly_mask(w, h, ellipses=[(42, 36, 62, 43)])
    rgb[emit] = LIME
    mask |= emit
    return add_outline(rgb, mask)


class UFO:
    def __init__(self):
        self.spr = build_ufo()
        self.lights = [(6 + i * 9, 25) for i in range(11)]

    def draw(self, cv, x, y, t, beam=0.0):
        """(x, y) top-left. Returns the emitter point."""
        cv.blit(self.spr, x, y)
        cols = [RED, YELLOW, LIME, CYAN, MAGENTA]
        for i, (lx, ly) in enumerate(self.lights):
            c = cols[(i + t // 4) % len(cols)]
            cv.rect(x + lx, y + ly, 2, 1, c)
        # emitter pulse
        if (t // 3) % 2 == 0:
            cv.rect(x + 49, y + 40, 8, 2, WHITE)
        return x + 53, y + 44
