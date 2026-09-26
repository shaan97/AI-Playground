"""MEGA MAW: a giant mechanical skull-dragon, built from bevel-shaded parts."""
import math

import numpy as np

from .engine import Sprite
from .palette import (AMBER, CRIMSON, GREY, INK, LEMON, MAGENTA, ORANGE, PINK, RED, ROSE, SILVER, STEEL,
                      WHITE, YELLOW, NIGHT, DEEP)
from .procgen import add_outline, bevel_shade, poly_mask, sphere

HULL = [(200, 184, 244), (156, 132, 218), (116, 92, 186), (86, 62, 150), (62, 40, 114), (42, 26, 82), (26, 16, 54)]
PLATE = [(226, 214, 255), (182, 162, 238), (140, 114, 206), (104, 78, 170), (74, 52, 132), (50, 32, 96)]
DARKHULL = [(116, 92, 186), (86, 62, 150), (62, 40, 114), (42, 26, 82), (30, 18, 60), (20, 12, 42)]
TOOTH = [WHITE, SILVER, (178, 184, 214), GREY, STEEL]
EYE = [WHITE, ROSE, PINK, (255, 64, 120), RED, CRIMSON, (110, 10, 50)]

BW, BH = 168, 108          # head sprite box
HINGE = (128.0, 64.0)

CRANIUM = [(6, 50), (18, 42), (34, 36), (50, 26), (70, 18), (92, 12), (118, 10), (140, 16), (152, 28),
           (152, 62), (128, 66), (60, 62), (28, 60), (8, 58)]
BROW = [(40, 31), (62, 22), (90, 19), (98, 26), (84, 31), (60, 36), (46, 37)]
CHEEK = [(98, 34), (132, 30), (148, 42), (132, 58), (102, 56), (94, 46)]
HORN_A = [(96, 15), (114, 6), (136, 0), (158, 1), (134, 8), (116, 17)]
HORN_B = [(126, 18), (146, 9), (166, 12), (148, 18), (136, 24)]
SNOUT_PLATE = [(10, 50), (22, 43), (36, 38), (46, 40), (34, 47), (18, 53)]
JAW = [(12, 64), (40, 63), (90, 65), (126, 63), (140, 71), (134, 84), (100, 90), (60, 88), (28, 81), (12, 72)]
EYE_C = (75, 44)


def _layer(w, h):
    return np.zeros((h, w, 3), np.uint8), np.zeros((h, w), bool)


def _paint(dst, dmask, rgb, mask):
    dst[mask] = rgb[mask]
    dmask |= mask


def _edge_y(poly, x, bottom=True):
    """y of the polygon's outline at column x (bottom-most or top-most crossing)."""
    ys = []
    n = len(poly)
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
        if (x0 - x) * (x1 - x) <= 0 and x0 != x1:
            t = (x - x0) / (x1 - x0)
            ys.append(y0 + (y1 - y0) * t)
    if not ys:
        return None
    return max(ys) if bottom else min(ys)


def _teeth(poly, x0, x1, step, length, pointing_down):
    tris = []
    x = x0
    while x < x1:
        y = _edge_y(poly, x + step / 2, bottom=pointing_down)
        if y is not None:
            ln = length * (0.75 + 0.25 * math.sin(x * 0.7))
            if pointing_down:
                tris.append([(x, y - 1), (x + step - 2, y - 1), (x + (step - 2) / 2, y + ln)])
            else:
                tris.append([(x, y + 1), (x + step - 2, y + 1), (x + (step - 2) / 2, y - ln)])
        x += step
    return tris


def _rot(pts, ang, c=HINGE):
    ca, sa = math.cos(ang), math.sin(ang)
    return [(c[0] + (x - c[0]) * ca - (y - c[1]) * sa, c[1] + (x - c[0]) * sa + (y - c[1]) * ca) for x, y in pts]


def build_head():
    rgb, mask = _layer(BW, BH)
    for poly, ramp in ((HORN_B, DARKHULL), (HORN_A, HULL)):
        m = poly_mask(BW, BH, polys=[poly])
        _paint(rgb, mask, bevel_shade(m, ramp), m)
    m = poly_mask(BW, BH, polys=[CRANIUM])
    _paint(rgb, mask, bevel_shade(m, HULL, grad=1.0), m)
    for poly, ramp in ((CHEEK, PLATE), (SNOUT_PLATE, PLATE), (BROW, PLATE)):
        m = poly_mask(BW, BH, polys=[poly])
        _paint(rgb, mask, bevel_shade(m, ramp), m)
    # outline between plates: dark seams
    for poly in (CHEEK, SNOUT_PLATE, BROW):
        m = poly_mask(BW, BH, polys=[poly])
        grown = np.zeros_like(m)
        grown[1:, :] |= m[:-1, :]
        grown[:, 1:] |= m[:, :-1]
        seam = grown & ~m & mask
        rgb[seam] = INK
    # upper teeth
    for tri in _teeth(CRANIUM, 16, 116, 9, 8, True):
        m = poly_mask(BW, BH, polys=[tri])
        _paint(rgb, mask, bevel_shade(m, TOOTH, edge=False), m)
    # eye socket
    ex, ey = EYE_C
    sock = poly_mask(BW, BH, ellipses=[(ex - 13, ey - 10, ex + 13, ey + 10)])
    rgb[sock] = NIGHT
    ring = poly_mask(BW, BH, ellipses=[(ex - 14, ey - 11, ex + 14, ey + 11)]) & ~sock
    rgb[ring & mask] = INK
    # neon trims
    for (x0, y0), (x1, y1) in (((46, 38), (60, 37)), ((100, 57), (130, 58)), ((22, 54), (34, 49))):
        n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
        for i in range(n):
            t = i / max(1, n - 1)
            rgb[int(round(y0 + (y1 - y0) * t)), int(round(x0 + (x1 - x0) * t))] = MAGENTA
    # vents on the cheek
    for k in range(4):
        rgb[40 + k * 4, 110:124] = INK
        rgb[41 + k * 4, 110:124] = (150, 40, 150)
    # rivets
    for (x, y) in ((56, 28), (80, 22), (104, 18), (126, 22), (140, 34), (140, 50), (112, 52), (26, 46)):
        rgb[y, x] = WHITE
        rgb[y + 1, x] = HULL[4]
    # nostrils
    rgb[47, 14:20] = INK
    rgb[48, 15:19] = MAGENTA
    return add_outline(rgb, mask)


def build_jaw(ang):
    poly = _rot(JAW, ang)
    rgb, mask = _layer(BW, BH + 30)
    m = poly_mask(BW, BH + 30, polys=[poly])
    _paint(rgb, mask, bevel_shade(m, HULL, grad=1.1), m)
    for tri in _teeth(JAW, 18, 112, 9, 7, False):
        tri = _rot(tri, ang)
        tm = poly_mask(BW, BH + 30, polys=[tri])
        _paint(rgb, mask, bevel_shade(tm, TOOTH, edge=False), tm)
    # neon stripe along the jaw
    stripe = _rot([(24, 78), (60, 82), (98, 84), (128, 76)], ang)
    for (x0, y0), (x1, y1) in zip(stripe[:-1], stripe[1:]):
        n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
        for i in range(n):
            t = i / max(1, n - 1)
            x, y = int(round(x0 + (x1 - x0) * t)), int(round(y0 + (y1 - y0) * t))
            if mask[y, x]:
                rgb[y, x] = MAGENTA
    return add_outline(rgb, mask)


def build_mouth(ang):
    """Throat polygon between the upper teeth line and the rotated jaw."""
    upper = [(10, 57), (60, 61), (128, 65)]
    lower = _rot([(12, 64), (40, 63), (90, 65), (126, 63)], ang)
    poly = upper + [HINGE] + list(reversed(lower))
    m = poly_mask(BW, BH + 30, polys=[poly])
    h, w = m.shape
    xx = np.broadcast_to(np.arange(w, dtype=np.float32)[None, :], (h, w))
    level = np.clip((xx - 10) / 118.0, 0, 1)            # darker toward the tip
    ramp = [(120, 20, 60), (92, 14, 52), (64, 10, 44), (40, 8, 34), (24, 6, 26)]
    from .procgen import _quantize
    rgb = _quantize((1 - level) * (len(ramp) - 1), ramp)
    rgb[~m] = 0
    return Sprite(rgb, m)


def build_neck_segment(w=46, h=62, ramp=HULL):
    rgb, mask = _layer(w, h)
    m = poly_mask(w, h, polys=[[(6, 4), (w - 10, 0), (w - 1, h // 2), (w - 10, h - 1), (6, h - 5), (0, h // 2)]])
    _paint(rgb, mask, bevel_shade(m, ramp, grad=1.0), m)
    band = poly_mask(w, h, rects=[(w // 2 - 3, 4, w // 2 + 2, h - 5)]) & m
    rgb[band] = bevel_shade(band, PLATE)[band]
    rgb[h // 2 - 1:h // 2 + 1, 8:w - 10][mask[h // 2 - 1:h // 2 + 1, 8:w - 10]] = MAGENTA
    return add_outline(rgb, mask)


class MegaMaw:
    def __init__(self):
        self.head = build_head()
        self.angles = [-math.radians(a) for a in range(0, 27, 2)]
        self.jaws = [build_jaw(a) for a in self.angles]
        self.mouths = [build_mouth(a) for a in self.angles]
        self.neck = [build_neck_segment(46, 62), build_neck_segment(44, 58, DARKHULL),
                     build_neck_segment(42, 54, DARKHULL)]
        self.eye_cache = {}
        self.turret = sphere(7, [ROSE, PINK, MAGENTA, (150, 40, 150), (90, 30, 110), DEEP])
        self.turret_dead = sphere(6, [GREY, STEEL, (70, 60, 90), (50, 40, 70), NIGHT])

    def eye_sprite(self, r):
        r = int(r)
        if r not in self.eye_cache:
            self.eye_cache[r] = sphere(r, EYE, outline=None)
        return self.eye_cache[r]

    def jaw_index(self, open_amt):
        return int(round(max(0.0, min(1.0, open_amt)) * (len(self.jaws) - 1)))

    # key points in head-local coordinates (for bullets / effects)
    @staticmethod
    def mouth_point(open_amt):
        return (20.0, 64.0 + 10 * open_amt)

    @staticmethod
    def eye_point():
        return EYE_C

    TURRET_TOP = (108, 6)
    TURRET_BOT = (84, 94)

    def turret_points(self, open_amt):
        (bx, by), = _rot([self.TURRET_BOT], self.angles[self.jaw_index(open_amt)])
        return self.TURRET_TOP, (bx, by)

    def draw(self, cv, x, y, t, open_amt=0.0, flash=False, eye_glow=0.0, turrets=(True, True),
             aim=(0.0, 0.0), charge=0.0, neck_phase=0.0, eye_alive=True, tint=None, eye_flash=False):
        """(x, y) is the top-left of the head box. t = frame counter.
        flash: solid white silhouette (reserved for single, one-off events).
        tint: (color, amount) steady colour wash for damage states.
        eye_flash: brief white eye when hit (small area, photosensitivity-safe)."""
        x, y = int(round(x)), int(round(y))
        fc = WHITE if flash else None
        tk = {"color": fc} if fc is not None else {"tint": tint}
        # neck segments trailing to the right (drawn back to front)
        for i in reversed(range(3)):
            seg = self.neck[i]
            sx = x + 138 + i * 36
            sy = y + 30 + int(round(math.sin(neck_phase + t * 0.05 - i * 0.9) * 3)) - (seg.h - 62) // 2
            cv.blit(seg, sx, sy, **tk)
        # mouth interior + jaw
        ji = self.jaw_index(open_amt)
        if ji > 0:
            cv.blit(self.mouths[ji], x, y, **tk)
            if charge > 0:
                gl = int(3 + 9 * charge)
                cx, cy = x + 44, y + 64 + 9 * open_amt
                cv.circle(cx, cy, gl, ORANGE)
                cv.circle(cx, cy, gl * 0.66, YELLOW)
                cv.circle(cx, cy, gl * 0.36, WHITE)
        cv.blit(self.jaws[ji], x - 1, y - 1, **tk)
        cv.blit(self.head, x - 1, y - 1, **tk)
        # eye
        ex, ey = EYE_C
        if eye_alive:
            pulse = 0.5 + 0.5 * math.sin(t * 0.25)
            r = 7 + (1 if pulse > 0.6 else 0) + int(round(eye_glow * 2))
            spr = self.eye_sprite(r)
            cv.blit(spr, x + ex - spr.w // 2, y + ey - spr.h // 2, color=WHITE if (flash or eye_flash) else None)
            # slit pupil that tracks the aim direction
            px = x + ex + int(round(max(-3, min(3, aim[0] * 3))))
            py = y + ey + int(round(max(-2, min(2, aim[1] * 2))))
            cv.rect(px - 1, py - 4, 2, 8, INK if not (flash or eye_flash) else PINK)
        else:
            cv.circle(x + ex, y + ey, 8, INK)
            cv.circle(x + ex, y + ey, 5, (60, 20, 40))
        # turrets
        (bx0, by0), = _rot([self.TURRET_BOT], self.angles[ji])
        for alive, (tx, ty) in zip(turrets, (self.TURRET_TOP, (bx0, by0))):
            spr = self.turret if alive else self.turret_dead
            if alive:
                ax, ay = aim
                n = math.hypot(ax, ay) or 1
                bx, by = x + tx + ax / n * 14, y + ty + ay / n * 14
                cv.thick_line(x + tx, y + ty, bx, by, 2, INK)
                cv.thick_line(x + tx, y + ty, bx, by, 1, SILVER)
                cv.pset(bx, by, WHITE)
            cv.blit(spr, x + tx - spr.w // 2, y + ty - spr.h // 2, **tk)
