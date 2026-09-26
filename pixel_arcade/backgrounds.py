"""Reusable backgrounds: starfields, synthwave sunset, nebula space."""
import math

import numpy as np

from .engine import W, H, dither_gradient
from .palette import (AMBER, CYAN, DEEP, ICE, INDIGO, INK, LEMON, MAGENTA, NIGHT, ORANGE, PINK, PURPLE,
                      ROSE, SCARLET, VIOLET, WHITE, YELLOW)
from . import procgen


class Starfield:
    def __init__(self, rng, n=160, layers=((0.15, (70, 70, 130)), (0.4, (150, 150, 210)), (1.0, WHITE)),
                 w=W, h=H):
        self.w, self.h = w, h
        self.x = rng.random(n) * w
        self.y = rng.random(n) * h
        self.layer = rng.integers(0, len(layers), n)
        self.speed = np.array([layers[i][0] for i in self.layer])
        self.color = [layers[i][1] for i in self.layer]
        self.tw = rng.random(n) * 6.28
        self.big = rng.random(n) < 0.06

    def draw(self, cv, t, vx=-1.0, vy=0.0, streak=0.0, y_limit=None, twinkle=True):
        """Scroll by (vx, vy) px/frame for the fastest layer; streak = warp line length factor."""
        xs = (self.x + vx * self.speed * t) % self.w
        ys = (self.y + vy * self.speed * t) % self.h
        for i in range(len(xs)):
            x, y = int(xs[i]), int(ys[i])
            if y_limit is not None and y >= y_limit:
                continue
            c = self.color[i]
            if twinkle and math.sin(t * 0.08 + self.tw[i]) > 0.85:
                c = CYAN if self.layer[i] == 2 else c
            if streak > 0:
                ln = int(streak * self.speed[i] * 2)
                if ln > 0:
                    cv.rect(x, y, ln, 1, tuple(v // 2 for v in c))
            cv.pset(x, y, c)
            if self.big[i] and self.layer[i] == 2:
                cv.pset(x - 1, y, tuple(v // 2 for v in c))
                cv.pset(x + 1, y, tuple(v // 2 for v in c))
                cv.pset(x, y - 1, tuple(v // 2 for v in c))
                cv.pset(x, y + 1, tuple(v // 2 for v in c))


# --------------------------------------------------------------------------
# Synthwave sunset (title screen)
# --------------------------------------------------------------------------
HORIZON = 136


def _ridge(rng, w, base, amp, rough=0.55, octaves=7):
    """1D midpoint-displacement ridge line (tileable)."""
    n = 2 ** octaves
    pts = np.zeros(n + 1)
    step = n
    scale = amp
    while step > 1:
        half = step // 2
        for i in range(half, n, step):
            pts[i] = (pts[i - half] + pts[(i + half) % (n + 1)]) / 2 + (rng.random() - 0.5) * scale
        step = half
        scale *= rough
    xs = np.linspace(0, n, w)
    return base + np.interp(xs, np.arange(n + 1), pts)


class Synthwave:
    def __init__(self, rng):
        self.sky = dither_gradient(HORIZON, W, [NIGHT, NIGHT, DEEP, INDIGO, PURPLE, VIOLET, MAGENTA, PINK,
                                                (255, 140, 150)])
        self.stars = Starfield(rng, 90, h=HORIZON - 40)
        edge = np.abs(np.arange(W) - W / 2) / (W / 2)          # 0 center .. 1 edges
        self.far = _ridge(rng, W, 0, 22) - (6 + 34 * edge ** 1.6) + HORIZON
        self.near = _ridge(rng, W, 0, 12) - (2 + 22 * edge ** 2.2) + HORIZON
        self.near = np.minimum(self.near, HORIZON - 1)
        self.far = np.minimum(self.far, HORIZON - 2)
        # sun gradient
        r = 50
        self.sun_r = r
        yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
        self.sun_mask = xx * xx + yy * yy <= r * r + r * 0.8
        t = np.clip((yy + r) / (1.05 * r), 0, 1)
        stops = [LEMON, YELLOW, AMBER, ORANGE, SCARLET, (255, 70, 120), MAGENTA]
        level = t * (len(stops) - 1)
        self.sun_rgb = procgen._quantize(level, stops)

    def draw_sky(self, cv, t):
        cv.px[:HORIZON] = self.sky
        self.stars.draw(cv, t, vx=-0.05, twinkle=True, y_limit=HORIZON - 40)

    def draw_sun(self, cv, t, cx=W // 2, cy=HORIZON):
        r = self.sun_r
        m = self.sun_mask.copy()
        top = cy - r
        vis = HORIZON - top                     # visible rows of the sun
        # classic stripe cut-outs in the lower part, drifting downward
        n = 7
        phase = (t * 0.02) % 1.0
        for i in range(n + 1):
            p = (i + phase) / n
            if p > 1:
                continue
            y = int(vis * 0.32 + p * vis * 0.68)
            thick = 1 + int(p * 3.2)
            m[y:y + thick] = False
        m[vis:] = False
        cv.mask_fill_rgb(m, self.sun_rgb, cx - r, top)

    def draw_mountains(self, cv, t, scroll=0.0):
        far = np.roll(self.far, -int(scroll * 0.3)).astype(int)
        near = np.roll(self.near, -int(scroll * 0.6)).astype(int)
        yy = np.arange(HORIZON)[:, None]
        sky = cv.px[:HORIZON]
        m_far = yy >= far[None, :]
        sky[m_far] = (88, 34, 128)
        sky[(yy >= far[None, :] + 3) & m_far] = (70, 26, 108)
        sky[yy == far[None, :]] = (196, 90, 210)
        sky[yy == far[None, :] + 1] = (130, 50, 160)
        m_near = yy >= near[None, :]
        sky[m_near] = (36, 14, 62)
        sky[yy == near[None, :]] = MAGENTA
        sky[yy == near[None, :] + 1] = (110, 30, 120)

    def draw_floor(self, cv, t, speed=1.0, glow=1.0):
        h = H - HORIZON
        cv.px[HORIZON:] = dither_gradient(h, W, [NIGHT, (30, 12, 56), (44, 16, 76)])
        vx = W / 2
        # horizontal lines with perspective, scrolling toward the viewer
        phase = (t * 0.035 * speed) % 1.0
        for k in range(10):
            z = (k + 1 - phase)
            if z <= 0:
                continue
            y = HORIZON + int(round(180.0 / (z * 2.2 + 0.5) ** 1.35))
            if y >= H or y <= HORIZON + 2:
                continue
            c = PINK if y > HORIZON + 30 else MAGENTA if y > HORIZON + 8 else (150, 40, 150)
            cv.rect(0, y, W, 1, c)
        # vertical lines radiating from the vanishing point
        for i in range(-16, 17):
            x_bottom = vx + i * 34
            cv.line(vx + i * 3, HORIZON + 1, x_bottom, H - 1, (180, 40, 170) if abs(i) > 5 else MAGENTA)
        # horizon glow
        cv.rect(0, HORIZON, W, 1, ROSE)
        cv.rect(0, HORIZON + 1, W, 1, MAGENTA)


# --------------------------------------------------------------------------
# Deep space with nebula clouds and a ringed planet
# --------------------------------------------------------------------------
class Space:
    def __init__(self, rng, width=768):
        self.width = width
        base = dither_gradient(H, width, [INK, NIGHT, (28, 16, 60), NIGHT, INK])
        n1, m1 = procgen.nebula_layer(H, width, [(168, 70, 176), (128, 48, 150), (96, 34, 124), (68, 24, 98),
                                                 (46, 18, 76), (32, 14, 58)], 11,
                                      scale=22, threshold=0.5, gain=1.35)
        n2, m2 = procgen.nebula_layer(H, width, [(56, 170, 190), (34, 124, 156), (26, 90, 128), (22, 62, 100),
                                                 (20, 44, 80), (18, 30, 62)], 23,
                                      scale=16, threshold=0.58, gain=1.4)
        img = base.copy()
        img[m2] = n2[m2]
        img[m1] = n1[m1]
        # soften: blend cloud colors toward the dark base with a dither mask for depth
        self.far = img
        self.stars_far = Starfield(rng, 120, layers=((0.25, (90, 90, 150)), (0.5, (160, 160, 220))), w=W)
        self.stars_near = Starfield(rng, 40, layers=((1.6, WHITE), (2.4, ICE)), w=W)
        self.planet = procgen.sphere(34, [ROSE, PINK, (238, 90, 170), VIOLET, PURPLE, DEEP, (24, 14, 50)],
                                     light=(-0.7, -0.4, 0.5))

    def draw(self, cv, t, speed=1.0, scroll_px=None, warp=0.0, planet=True):
        off = int(scroll_px if scroll_px is not None else t * 0.25 * speed) % self.width
        if off + W <= self.width:
            cv.px[:] = self.far[:, off:off + W]
        else:
            k = self.width - off
            cv.px[:, :k] = self.far[:, off:]
            cv.px[:, k:] = self.far[:, :W - k]
        if planet:
            px = int(330 - t * 0.3)
            if px > -80:
                self._draw_planet(cv, px, 62)
        self.stars_far.draw(cv, t, vx=-1.2 * speed, streak=warp * 3)
        self.stars_near.draw(cv, t, vx=-2.2 * speed, streak=1.5 + warp * 8, twinkle=False)

    def _draw_planet(self, cv, x, y):
        p = self.planet
        # back half of the ring
        self._ring(cv, x, y, back=True)
        cv.blit(p, x - p.w // 2, y - p.h // 2)
        self._ring(cv, x, y, back=False)

    @staticmethod
    def _ring(cv, cx, cy, back):
        for k, (rx, col) in enumerate(((58, (255, 200, 120)), (54, AMBER), (50, (200, 110, 60)))):
            ry = rx * 0.22
            n = 220
            for i in range(n):
                a = i / n * math.tau
                s = math.sin(a)
                if (s < 0) != back:
                    continue
                x = cx + math.cos(a) * rx
                y = cy + s * ry - math.cos(a) * rx * 0.18
                cv.pset(x, y, col)
