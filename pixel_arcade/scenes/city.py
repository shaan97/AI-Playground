"""STAGE 1 - NEON CITY: a rooftop run choreographed to the beat, ending with
the Star Core being stolen by a UFO and Comet Kid blasting off after it."""
import math

import numpy as np

from ..backgrounds import Starfield
from ..engine import (W, H, Particles, clamp, dither_gradient, ease_in_cubic, ease_in_out, ease_out_cubic,
                      lerp, shake_offset, shift_canvas, star_glint)
from ..hero import Hero
from ..palette import (AMBER, CYAN, DEEP, FIRE, GOLDEN, INDIGO, INK, LIME, MAGENTA, NEON_PINK, NIGHT, ORANGE,
                       PINK, PLASMA, PURPLE, RAINBOW, RED, SILVER, SKY, SMOKE, TOXIC, VIOLET, WHITE,
                       YELLOW, BROWN, RUST, CREAM)
from ..procgen import sphere
from ..props import UFO, StarCore, draw_tower
from ..scene import Scene, card, draw_hud
from ..engine import Sprite
from ..sprites import BUG, COIN, CRATE, DRONE, HERO, PLAYER_SHIP, STAR_SHARD

B = 24                      # frames per beat
SPEED = 2.0                 # hero run speed (px/frame)
X0 = 60                     # hero world x at f=0
HERO_SCREEN_X = 110
RUN_END = 32 * B            # hero stops running after 8 bars
CAM_END = X0 + SPEED * RUN_END - HERO_SCREEN_X + 14
TOWER_X = 470               # in far-layer coordinates (parallax 0.12)
TOWER_TOP = 92

# roof segments: (x0, x1, y_top)
ROOFS = [(-300, 270, 176), (310, 620, 160), (640, 840, 144), (1000, 1320, 160), (1350, 1440, 144),
         (1480, 2400, 176)]

# hero choreography: ('run', f0, f1, y) | ('arc', f0, f1, y0, y1, apex)
MOVES = [
    ("run", 0, 4 * B, 176),
    ("arc", 4 * B, 5.5 * B, 176, 160, 30),
    ("run", 5.5 * B, 8 * B, 160),
    ("arc", 8 * B, 9 * B, 160, 147, 16),       # onto bug 1
    ("arc", 9 * B, 10.5 * B, 147, 160, 34),    # bounce
    ("run", 10.5 * B, 11.5 * B, 160),
    ("arc", 11.5 * B, 12.5 * B, 160, 144, 22),
    ("run", 12.5 * B, 16 * B, 144),            # crate at 13, shard at 14
    ("arc", 16 * B, 17 * B, 144, 132, 22),     # drone 1
    ("arc", 17 * B, 18 * B, 132, 122, 26),     # drone 2
    ("arc", 18 * B, 19 * B, 122, 132, 26),     # drone 3
    ("arc", 19 * B, 20.5 * B, 132, 160, 30),
    ("run", 20.5 * B, 26 * B, 160),            # smash bugs at 24, 25
    ("arc", 26 * B, 27.5 * B, 160, 144, 32),
    ("run", 27.5 * B, 28 * B, 144),
    ("arc", 28 * B, 29 * B, 144, 120, 26),
    ("arc", 29 * B, 30.5 * B, 120, 176, 30),   # double jump
    ("run", 30.5 * B, 32 * B, 176),
]
STOMPS = [9 * B, 17 * B, 18 * B, 19 * B]
COMET_START, COMET_END = 14 * B, 32 * B

# story beats (local frames)
ALARM = 36 * B
BEAM_ON = 38 * B
ABSORB = 41 * B + 12
UFO_LEAVE = 42 * B
SHIP_IN = 44 * B
BOARD = 45 * B
IGNITE = 46 * B
LAUNCH = 46 * B + 12


def hero_x(f):
    if f <= RUN_END:
        return X0 + SPEED * f
    # decelerate over 1.5 beats
    k = clamp((f - RUN_END) / (1.5 * B))
    return X0 + SPEED * RUN_END + SPEED * 1.5 * B * (k - k * k / 2)


def hero_y(f):
    """Returns (y, vy, airborne)."""
    for m in MOVES:
        if m[0] == "run" and m[1] <= f < m[2]:
            return m[3], 0.0, False
        if m[0] == "arc" and m[1] <= f < m[2]:
            _, f0, f1, y0, y1, h = m
            T = f1 - f0
            s = (f - f0) / T
            y = lerp(y0, y1, s) - 4 * h * s * (1 - s)
            vy = (y1 - y0) / T - 4 * h * (1 - 2 * s) / T
            return y, vy, True
    return 176, 0.0, False


def roof_at(x):
    for x0, x1, y in ROOFS:
        if x0 <= x < x1:
            return y
    return None


# --------------------------------------------------------------------------
# background layers (pre-rendered strips)
# --------------------------------------------------------------------------

def _skyline(rng, width, h_min, h_max, w_min, w_max, body, edge, win_cols, win_p, win=(1, 1), gap=(2, 3),
             spires=0.2, clear=()):
    rgb = np.zeros((H, width, 3), np.uint8)
    mask = np.zeros((H, width), bool)
    x = -10
    lights = []
    while x < width:
        bw = int(rng.integers(w_min, w_max))
        bh = int(rng.integers(h_min, h_max))
        for (c0, c1, cmax) in clear:        # keep a plaza open around the tower
            if x < c1 and x + bw > c0:
                bh = min(bh, cmax)
        top = H - bh
        x0, x1 = max(0, x), min(width, x + bw)
        if x1 > x0:
            rgb[top:, x0:x1] = body
            mask[top:, x0:x1] = True
            rgb[top, x0:x1] = edge
            # setback roof
            if rng.random() < 0.35 and bw > 16:
                sw = bw // 2
                sx = x + bw // 4
                sh = int(rng.integers(6, 18))
                a, b = max(0, sx), min(width, sx + sw)
                if b > a:
                    rgb[top - sh:top, a:b] = body
                    mask[top - sh:top, a:b] = True
                    rgb[top - sh, a:b] = edge
                    if rng.random() < spires and not any(x < c1 and x + bw > c0 for c0, c1, _ in clear):
                        mx = (a + b) // 2
                        sp = int(rng.integers(8, 22))
                        rgb[top - sh - sp:top - sh, mx] = edge
                        mask[top - sh - sp:top - sh, mx] = True
                        lights.append((mx, top - sh - sp - 1))
            # windows
            wx, wy = win
            gx, gy = gap
            for yy in range(top + 3, H - 2, wy + gy):
                for xx in range(x0 + 2, x1 - wx - 1, wx + gx):
                    if rng.random() < win_p:
                        c = win_cols[int(rng.integers(0, len(win_cols)))]
                        rgb[yy:yy + wy, xx:xx + wx] = c
        x += bw + int(rng.integers(0, 3))
    return rgb, mask, lights


def _foreground(rng, width):
    rgb = np.zeros((H, width, 3), np.uint8)
    mask = np.zeros((H, width), bool)
    lights = []
    signs = []
    facade = [(58, 42, 100), (46, 32, 84), (38, 26, 70), (30, 20, 58)]
    for (x0, x1, y) in ROOFS:
        a, b = max(0, x0 + 300), min(width, x1 + 300)   # strip offset: world x + 300
        if b <= a:
            continue
        g = dither_gradient(H - y, b - a, facade, ox=a)
        rgb[y:, a:b] = g
        mask[y:, a:b] = True
        # ledge
        rgb[y:y + 4, a:b] = (104, 84, 160)
        rgb[y, a:b] = (184, 164, 236)
        rgb[y + 3, a:b] = (60, 44, 104)
        # side edges
        rgb[y:, a] = (140, 120, 200)
        rgb[y:, b - 1] = (20, 12, 40)
        rgb[y:, a + 1] = (70, 54, 120)
        # windows
        for wy in range(y + 10, H - 4, 12):
            for wx in range(a + 6, b - 10, 14):
                lit = rng.random() < 0.55
                col = [(255, 206, 120), (255, 150, 200), (140, 230, 255)][int(rng.integers(0, 3))] if lit \
                    else (22, 14, 44)
                rgb[wy:wy + 6, wx:wx + 6] = (20, 12, 40)
                rgb[wy + 1:wy + 6, wx + 1:wx + 6] = col
                if lit:
                    rgb[wy + 1, wx + 1:wx + 6] = tuple(min(255, c + 40) for c in col)
                    rgb[wy + 3, wx + 1:wx + 6] = tuple(int(c * 0.8) for c in col)
        # roof props
        px = a + 18
        while px < b - 30:
            kind = rng.random()
            if kind < 0.28:      # AC unit
                rgb[y - 9:y, px:px + 14] = (120, 128, 170)
                rgb[y - 9, px:px + 14] = (190, 196, 230)
                rgb[y - 1, px:px + 14] = (60, 64, 100)
                for k in range(px + 2, px + 12, 2):
                    rgb[y - 7:y - 2, k] = (70, 76, 116)
                mask[y - 9:y, px:px + 14] = True
                px += 26
            elif kind < 0.45:    # antenna
                h = int(rng.integers(14, 30))
                rgb[y - h:y, px + 2] = (150, 150, 190)
                rgb[y - h // 2, px:px + 5] = (150, 150, 190)
                mask[y - h:y, px + 2] = True
                mask[y - h // 2, px:px + 5] = True
                lights.append((px + 2 - 300, y - h - 1))
                px += 22
            elif kind < 0.6:     # water tank
                rgb[y - 22:y - 6, px:px + 16] = (150, 80, 60)
                rgb[y - 22:y - 6, px + 1:px + 4] = (200, 120, 80)
                rgb[y - 22:y - 6, px + 13:px + 16] = (100, 50, 50)
                rgb[y - 24:y - 22, px + 1:px + 15] = (110, 60, 50)
                for k in (y - 18, y - 11):
                    rgb[k, px:px + 16] = (80, 40, 40)
                rgb[y - 6:y, px + 2] = (80, 70, 110)
                rgb[y - 6:y, px + 13] = (80, 70, 110)
                mask[y - 24:y - 6, px:px + 16] = True
                mask[y - 6:y, px + 2] = True
                mask[y - 6:y, px + 13] = True
                px += 30
            elif kind < 0.72:    # railing
                ln = int(rng.integers(20, 40))
                e = min(px + ln, b - 4)
                rgb[y - 7, px:e] = (130, 120, 180)
                mask[y - 7, px:e] = True
                for k in range(px, e, 6):
                    rgb[y - 7:y, k] = (130, 120, 180)
                    mask[y - 7:y, k] = True
                px = e + 10
            else:
                px += 16
    # billboards with neon text (drawn live for flicker)
    for wx, y, text, col in ((520, 160, "ARCADE", PINK), (1100, 160, "PIXEL", CYAN), (1700, 176, "24H", LIME),
                             (80, 176, "RAMEN", AMBER)):
        a = wx + 300
        w = len(text) * 6 + 10
        top = y - 34
        rgb[top:top + 20, a:a + w] = (24, 14, 44)
        rgb[top, a:a + w] = (90, 70, 140)
        rgb[top + 19, a:a + w] = (60, 44, 100)
        rgb[top:top + 20, a] = (90, 70, 140)
        rgb[top:top + 20, a + w - 1] = (60, 44, 100)
        rgb[top + 20:y, a + 4] = (90, 80, 130)
        rgb[top + 20:y, a + w - 5] = (90, 80, 130)
        mask[top:top + 20, a:a + w] = True
        mask[top + 20:y, a + 4] = True
        mask[top + 20:y, a + w - 5] = True
        signs.append((wx + 5, top + 6, text, col))
    return rgb, mask, lights, signs


class City(Scene):
    def __init__(self, ctx, n):
        super().__init__(ctx, n)
        rng = self.rng
        self.sky = dither_gradient(H, W, [INK, NIGHT, DEEP, INDIGO, PURPLE, (126, 52, 150), (190, 76, 160)])
        self.stars = Starfield(rng, 110, h=130)
        self.moon = sphere(15, [WHITE, CREAM, (236, 226, 255), SILVER, (170, 170, 214), (120, 118, 170)],
                           light=(-0.8, -0.3, 0.5))
        self.far, self.far_m, self.far_lights = _skyline(rng, 1000, 50, 118, 14, 34, (50, 32, 96), (84, 58, 140),
                                                         [(180, 150, 90), (110, 170, 200), (150, 110, 170)],
                                                         0.22, win=(1, 1), gap=(2, 3), clear=[(780, 900, 58)])
        self.mid, self.mid_m, self.mid_lights = _skyline(rng, 1300, 60, 150, 26, 54, (34, 22, 66),
                                                         (74, 52, 120),
                                                         [(255, 200, 120), (255, 130, 200), (130, 220, 255)],
                                                         0.35, win=(2, 2), gap=(3, 4), spires=0.5,
                                                         clear=[(950, 1175, 64)])
        self.mid_signs = []
        for i in range(9):
            sx = 60 + i * 140 + int(rng.integers(-20, 20))
            if 930 < sx < 1190:
                sx += 260
            txt = ["HOTEL", "BAR", "CAFE", "NEON", "GAME", "KARAOKE", "BYTE", "NOODLE", "DISCO"][i]
            col = [PINK, CYAN, AMBER, MAGENTA, LIME, PINK, CYAN, ORANGE, VIOLET][i]
            self.mid_signs.append((sx, 60 + int(rng.integers(0, 50)), txt, col, i % 3 == 0))
        self.fg, self.fg_m, self.fg_lights, self.signs = _foreground(rng, 2800)
        self.hero = Hero()
        self.parts = Particles(5000)
        self.ufo = UFO()
        self.star = StarCore()
        self.popups = []
        self.prev_cam = None
        self.shake = 0.0
        self.coin_streak = 0
        self.last_coin = -99
        self.ghosts = []
        self.lights_on = 1.0
        self._build_entities()

    # ------------------------------------------------------------------
    def _build_entities(self):
        coins = []

        def add_coin_at_frame(f, dy=-10):
            y, _, _ = hero_y(f)
            coins.append({"x": hero_x(f) + 8, "y": y + dy, "f": int(f), "got": False})

        for k in range(3, 8):                 # roof A line on 8th notes
            add_coin_at_frame(12 * k)
        for f in range(102, 132, 6):          # arc over gap 1 (16ths)
            add_coin_at_frame(f)
        for f in range(222, 252, 6):          # bounce arc after bug 1
            add_coin_at_frame(f)
        for f in range(21 * B, 24 * B, 12):   # roof D line
            add_coin_at_frame(f)
        for f in range(26 * B + 6, 27 * B + 12, 6):
            add_coin_at_frame(f)
        for f in range(29 * B + 3, 30 * B, 6):
            add_coin_at_frame(f)
        self.coins = coins
        # enemies
        self.bugs = []
        f = STOMPS[0]
        self.bugs.append({"xs": hero_x(f), "fs": f, "y": 160, "kind": "stomp", "dead": None})
        for f in (24 * B, 25 * B):
            self.bugs.append({"xs": hero_x(f) + 14, "fs": f, "y": 160, "kind": "smash", "dead": None})
        self.drones = []
        for f in STOMPS[1:]:
            y, _, _ = hero_y(f)
            self.drones.append({"x": hero_x(f), "y": y, "fs": f, "dead": None})
        self.crate = {"x": hero_x(13 * B) + 14, "y": 144 - 13, "f": 13 * B, "broken": False}
        self.shard_got = False

    # ------------------------------------------------------------------
    def camera(self, f):
        if f <= RUN_END:
            return hero_x(f) - HERO_SCREEN_X
        k = ease_out_cubic(clamp((f - RUN_END) / 40))
        return lerp(hero_x(RUN_END) - HERO_SCREEN_X, CAM_END, k)

    def popup(self, text, x, y, f, col=WHITE):
        self.popups.append({"t": text, "x": x, "y": y, "f": f, "c": col})

    def draw_backdrop(self, cv, f, cam, theft=True):
        cv.px[:] = self.sky
        self.stars.draw(cv, f, vx=0.0)
        mx = 64 - int(cam * 0.02)
        cv.blit(self.moon, mx, 22)
        # searchlights from the tower
        tx = int(TOWER_X - cam * 0.12)
        if self.lights_on > 0.5:
            for i in range(2):
                a = -math.pi / 2 + math.sin(f * 0.012 + i * 2.2) * 0.7
                for r in range(10, 170, 1):
                    x = tx + math.cos(a) * r
                    y = TOWER_TOP - 8 + math.sin(a) * r
                    half = r * 0.07
                    for d in range(-int(half), int(half) + 1):
                        px, py = x + d * math.cos(a + math.pi / 2), y + d * math.sin(a + math.pi / 2)
                        if 0 <= px < W and 0 <= py < H and ((int(px) + int(py)) % 2 == 0):
                            c = cv.px[int(py), int(px)]
                            cv.px[int(py), int(px)] = np.minimum(255, c.astype(int) + 28)
        # far skyline
        off = int(cam * 0.25) + 200
        seg = self.far[:, off:off + W]
        m = self.far_m[:, off:off + W]
        if not self.lights_on > 0.5:
            seg = (seg.astype(np.float32) * [0.6, 0.6, 0.8]).astype(np.uint8)
        cv.px[m] = seg[m]
        # the tower with the Star Core
        draw_tower(cv, tx, H, TOWER_TOP, f, lit=self.lights_on > 0.5)
        if theft:
            self.draw_theft(cv, f, cam)
        else:
            self.backdrop_hook(cv, f, tx)
        # mid skyline
        off = int(cam * 0.5) + 100
        seg = self.mid[:, off:off + W]
        m = self.mid_m[:, off:off + W]
        if self.lights_on < 0.5:
            dark = seg.copy()
            bright = seg.max(-1) > 110
            dark[bright] = (40, 28, 70)
            seg = dark
        cv.px[m] = seg[m]
        for (sx, sy, txt, col, vert) in self.mid_signs:
            x = sx - off
            if -40 < x < W + 10:
                on = self.lights_on > 0.5 and not (((f // 3) + sx) % 47 == 0)
                c = col if on else (60, 40, 80)
                if vert:
                    for i, ch in enumerate(txt[:6]):
                        cv.text(ch, x, sy + i * 8, c, shadow=INK if on else None)
                else:
                    cv.text(txt, x, sy, c, shadow=INK if on else None)
        for (lx, ly) in self.mid_lights:
            x = lx - off
            if 0 <= x < W and (f // 20 + lx) % 3 == 0:
                cv.pset(x, ly, RED)

    def backdrop_hook(self, cv, f, tx):
        """Extra drawing between the tower and the mid skyline (used by the ending)."""

    def draw_foreground(self, cv, f, cam):
        off = int(round(cam)) + 300
        seg = self.fg[:, off:off + W]
        m = self.fg_m[:, off:off + W]
        if self.lights_on < 0.5:
            seg = seg.copy()
            bright = seg.max(-1) > 170
            win = bright & (np.arange(H)[:, None] > 150)
            seg[win] = (30, 20, 50)
        cv.px[m] = seg[m]
        for (sx, sy, txt, col) in self.signs:
            x = sx - int(round(cam))
            if -60 < x < W:
                on = self.lights_on > 0.5 and (f // 2 + sx) % 61 not in (0, 1, 3)
                cv.text(txt, x, sy, col if on else (50, 36, 70), shadow=None)
        for (lx, ly) in self.fg_lights:
            x = lx - int(round(cam))
            if 0 <= x < W and (f // 15) % 2 == 0:
                cv.pset(x, ly, RED)
                cv.pset(x, ly - 1, (255, 120, 120))

    # ------------------------------------------------------------------
    def render(self, f):
        cv, ctx, rng = self.cv, self.ctx, self.rng
        cam = self.camera(f)
        if self.prev_cam is not None:
            self.parts.shift(-(cam - self.prev_cam))
        self.prev_cam = cam
        icam = int(round(cam))

        # power failure after the theft
        if f >= ABSORB:
            self.lights_on = 0.0 if (f - ABSORB) > 20 or (f // 3) % 2 else 1.0

        self.draw_backdrop(cv, f, cam)
        self.draw_foreground(cv, f, cam)

        # ---------------- hero kinematics ----------------
        hx = hero_x(f)
        hy, vy, air = hero_y(f)
        comet = COMET_START <= f < COMET_END
        if f >= RUN_END:
            hy, vy, air = 176, 0.0, False
        hsx = hx - icam

        # jump / land events
        for m in MOVES:
            if m[0] == "arc" and int(m[1]) == f and f not in STOMPS:
                ctx.sfx("jump", pan=hsx / W * 2 - 1)
            if m[0] == "run" and int(m[1]) == f and f > 0:
                ctx.sfx("land", pan=hsx / W * 2 - 1)
                self.parts.burst(rng, hsx + 8, m[3], 10, 1.2, 16, SMOKE, spread=math.pi, angle=-math.pi / 2,
                                 size=1.2, drag=0.1)
        if f in (29 * B,):
            ctx.sfx("double_jump")
            self.parts.burst(rng, hsx + 8, hy, 24, 2.0, 20, PLASMA, drag=0.08)

        # ---------------- coins ----------------
        for c in self.coins:
            sx = c["x"] - icam
            if c["got"] or sx < -20 or sx > W + 20:
                if not c["got"] and f >= c["f"]:
                    c["got"] = True
                continue
            if f >= c["f"]:
                c["got"] = True
                self.coin_streak = self.coin_streak + 1 if f - self.last_coin < 20 else 0
                self.last_coin = f
                ctx.sfx("coin", pitch=min(self.coin_streak, 12), pan=sx / W * 2 - 1)
                ctx.add_score(100)
                self.parts.burst(rng, sx, c["y"], 8, 1.4, 14, GOLDEN, drag=0.1)
                continue
            fr = COIN[((f + int(c["x"])) // 5) % 4]
            cv.blit(fr, sx - 4, c["y"] - 4 + math.sin(f * 0.1 + c["x"]) * 1.0)

        # ---------------- crate + star shard ----------------
        cr = self.crate
        if not cr["broken"]:
            sx = cr["x"] - icam
            if -20 < sx < W:
                cv.blit(CRATE, sx, cr["y"])
                if (f // 8) % 6 == 0:
                    star_glint(cv, sx + 3, cr["y"] + 2, 2, WHITE)
            if f >= cr["f"]:
                cr["broken"] = True
                ctx.sfx("crate", pan=sx / W * 2 - 1)
                ctx.add_score(500)
                self.shake = 3
                self.popup("500", cr["x"] + 7, cr["y"] - 4, f)
                self.parts.burst(rng, sx + 7, cr["y"] + 6, 40, 2.6, 30, GOLDEN, grav=0.12, drag=0.02)
                self.parts.burst(rng, sx + 7, cr["y"] + 6, 14, 2.0, 40, [AMBER, ORANGE, RUST, BROWN],
                                 grav=0.15, size=1.5, drag=0.02)
        if cr["broken"] and not self.shard_got:
            t0, t1 = cr["f"], COMET_START
            k = (f - t0) / (t1 - t0)
            sx0, sy0 = cr["x"] + 7 - icam, cr["y"] + 4
            tx, ty = hx + 8 - icam, hy - 12
            x = lerp(sx0, tx, k)
            y = lerp(sy0, ty, k) - 34 * 4 * k * (1 - k)
            cv.blit(STAR_SHARD, x - 4, y - 5)
            if f % 2 == 0:
                self.parts.emit(x, y, rng.normal(0, 0.4), rng.normal(0, 0.4), 18, GOLDEN)
            if f >= t1:
                self.shard_got = True
                ctx.sfx("powerup")
                ctx.add_score(1000)
                self.popup("COMET MODE!", hx + 8, hy - 30, f, YELLOW)
                self.parts.burst(rng, tx, ty, 60, 3.2, 30, PLASMA, drag=0.06)
                self.parts.burst(rng, tx, ty, 30, 2.0, 30, GOLDEN, drag=0.06)

        # ---------------- bugs ----------------
        for bug in self.bugs:
            fs = bug["fs"]
            bx = bug["xs"] + 0.45 * (fs - f) if bug["dead"] is None else bug["bx"]
            sx = bx - icam
            if bug["dead"] is None:
                if f >= fs:
                    bug["dead"] = f
                    bug["bx"] = bx
                    if bug["kind"] == "stomp":
                        ctx.sfx("stomp", pan=sx / W * 2 - 1)
                        ctx.add_score(200)
                        self.popup("200", bx + 8, bug["y"] - 20, f)
                    else:
                        ctx.sfx("smash", pan=sx / W * 2 - 1)
                        ctx.add_score(1000)
                        self.popup("1000", bx + 8, bug["y"] - 20, f, CYAN)
                        self.shake = 3
                        self.parts.burst(rng, sx + 8, bug["y"] - 8, 30, 3.0, 24, FIRE, drag=0.06)
                elif -20 < sx < W + 20:
                    cv.blit(BUG[(f // 8) % 2], sx, bug["y"] - BUG[0].h)
            if bug["dead"] is not None:
                dt = f - bug["dead"]
                if bug["kind"] == "stomp":
                    if dt < 18:
                        spr = BUG[0]
                        h = max(3, spr.h - 10)
                        squash = spr.rgb[-h:], spr.mask[-h:]
                        cv.blit(Sprite(squash[0], squash[1]), sx, bug["y"] - h)
                    if dt == 18:
                        self.parts.burst(rng, sx + 8, bug["y"] - 3, 16, 1.5, 20, NEON_PINK, drag=0.08)
                else:
                    if dt < 60:
                        x = sx + dt * 3.0
                        y = bug["y"] - 14 - dt * 4 + 0.25 * dt * dt
                        spr = BUG[0].flipped_v() if (dt // 4) % 2 else BUG[0]
                        cv.blit(spr, x, y)
                        if dt % 3 == 0:
                            self.parts.emit(x + 8, y + 6, rng.normal(0, 0.4), rng.normal(0, 0.4), 16, SMOKE,
                                            size=1.5)

        # ---------------- drones ----------------
        chain = [200, 400, 800]
        for i, d in enumerate(self.drones):
            fs = d["fs"]
            sx = d["x"] - icam
            if d["dead"] is None:
                if f >= fs:
                    d["dead"] = f
                    ctx.sfx("stomp", pan=sx / W * 2 - 1, chain=i)
                    ctx.add_score(chain[i])
                    self.popup(str(chain[i]), d["x"] + 8, d["y"] - 14, f, [WHITE, YELLOW, CYAN][i])
                    self.parts.burst(rng, sx + 8, d["y"] + 8, 36, 2.4, 26, FIRE, drag=0.05)
                    self.parts.burst(rng, sx + 8, d["y"] + 8, 10, 1.2, 30, SMOKE, size=2.0, drag=0.05)
                    self.shake = max(self.shake, 2)
                elif -20 < sx < W + 20:
                    bob = 2 * math.sin((f - fs) * 0.12)
                    cv.blit(DRONE[(f // 3) % 2], sx, d["y"] + bob)
                    if f % 4 == 0:
                        self.parts.emit(sx + 6 + rng.random() * 4, d["y"] + 15 + bob, 0, 0.8, 8, PLASMA)

        # ---------------- hero draw ----------------
        if f < BOARD + 14:
            pose = ("jump" if vy < 0 else "fall") if air else ("run" if f < RUN_END + 30 else "stand")
            if RUN_END <= f < RUN_END + 36 and f % 3 == 0:
                self.parts.emit(hsx + 4, 175, rng.normal(-0.8, 0.3), -0.4, 16, SMOKE, size=1.2)
            if f == RUN_END + 4:
                ctx.sfx("skid")
            # boarding the ship: an arc into the cockpit
            bx, by = hsx, hy
            if f >= BOARD:
                k = (f - BOARD) / 14
                shipx, shipy = self.ship_pos(f)
                bx = lerp(hsx, shipx + 10, k)
                by = lerp(176, shipy + 6, k) - 30 * 4 * k * (1 - k)
                pose = "jump" if k < 0.5 else "fall"
                vy = -2 if k < 0.5 else 2
            # comet mode afterimages: solid rainbow silhouettes (stored in world coordinates)
            if comet:
                self.ghosts.append((bx + icam, by))
                self.ghosts = self.ghosts[-13:]
                trail = [self.ghosts[-1 - k] for k in (12, 8, 4) if len(self.ghosts) > k]
                for gi, (gx, gy) in enumerate(trail):          # oldest first, newest on top
                    col = RAINBOW[(f // 3 + gi * 3) % len(RAINBOW)]
                    for part, oy in (("legs_stand", 16), ("torso_fwd", 11), ("head", 0)):
                        cv.blit(HERO[part], gx - icam, gy - 22 + oy, color=col)
                if f % 2 == 0:
                    k = (f // 2) % len(RAINBOW)
                    self.parts.emit(bx + 4, by - 8 + rng.random() * 8, -1.2, rng.normal(0, 0.3), 20,
                                    RAINBOW[k:] + RAINBOW[:k])
            flash = None
            if comet and f % 12 < 2:
                flash = (255, 250, 200)
            vx_eff = SPEED if f < RUN_END + 20 else 1.2
            arm = None
            if ALARM + 30 <= f < BOARD and (f // 12) % 2 == 0 and f > UFO_LEAVE:
                arm = "torso_up"
            self.hero.draw(cv, bx, by, pose=pose, frame=f, vx=vx_eff, vy=vy, flash=flash, arm=arm)
            # exclamation bubble
            if ALARM <= f < ALARM + 40 or UFO_LEAVE + 10 <= f < UFO_LEAVE + 50:
                txt = "!" if f < UFO_LEAVE else "!!"
                cv.rect(bx + 4, by - 36, 5 + 6 * len(txt), 11, WHITE)
                cv.rect_outline(bx + 3, by - 37, 7 + 6 * len(txt), 13, INK)
                cv.text(txt, bx + 6, by - 34, RED, shadow=None)

        # ---------------- the ship ----------------
        self.draw_ship(cv, f)

        # ---------------- particles, popups ----------------
        self.parts.update()
        self.parts.draw(cv)
        alive = []
        for p in self.popups:
            dt = f - p["f"]
            if dt < 40:
                alive.append(p)
                y = p["y"] - dt * 0.6
                if dt < 30 or (f // 2) % 2 == 0:
                    cv.text(p["t"], p["x"] - icam, y, p["c"], shadow=INK, align="center")
        self.popups = alive

        # shake
        if self.shake > 0.3:
            dx, dy = shake_offset(rng, self.shake)
            shift_canvas(cv, dx, dy)
        self.shake *= 0.85

        # HUD + stage card
        draw_hud(cv, ctx, "heart", f)
        coins_got = sum(c["got"] for c in self.coins)
        cv.blit(COIN[0], W - 44, 20)
        cv.text(f"x{coins_got:02d}", W - 34, 21, WHITE)
        card(cv, "STAGE 1", "NEON CITY", f / (2 * 96 - 12))

        post = {"bloom": 1.0}
        if f >= self.n - 10:
            cv.flash((f - (self.n - 10)) / 10)
        return cv, post

    # ------------------------------------------------------------------
    def ship_pos(self, f):
        """Screen position (top-left) of the player's ship during the launch."""
        hx_end = hero_x(RUN_END + 60) - CAM_END
        park = (hx_end + 26, 150)
        if f < SHIP_IN:
            return -60, 60
        if f < BOARD:
            k = ease_out_cubic((f - SHIP_IN) / (BOARD - SHIP_IN))
            return lerp(-60, park[0], k), lerp(40, park[1], k) + math.sin(k * math.pi) * -20
        if f < LAUNCH:
            shake = (f % 2) * (1 if f >= IGNITE else 0)
            return park[0] + shake, park[1] + math.sin(f * 0.2) * 1.0
        k = (f - LAUNCH) / 30.0
        return park[0] + 500 * ease_in_cubic(min(k, 1.2)), park[1] - 260 * ease_in_cubic(min(k, 1.2))

    def draw_theft(self, cv, f, cam):
        rng, ctx = self.rng, self.ctx
        tx = int(TOWER_X - cam * 0.12)
        star_y = TOWER_TOP - 12
        # star core on the tower (until absorbed)
        if f < BEAM_ON + 24:
            self.star.draw(cv, tx, star_y, f)
        # UFO
        ux, uy = tx - 53, -60
        if ALARM <= f < UFO_LEAVE + 50:
            if f == ALARM:
                ctx.sfx("alarm")
            if f < BEAM_ON:
                k = ease_out_cubic((f - ALARM) / (BEAM_ON - ALARM))
                uy = lerp(-60, 4, k)
            elif f < UFO_LEAVE:
                uy = 4 + math.sin(f * 0.1) * 1.5
            else:
                k = (f - UFO_LEAVE) / 40
                ux = tx - 53 + 360 * ease_in_cubic(k)
                uy = 4 - 110 * ease_in_cubic(k)
                if f == UFO_LEAVE:
                    ctx.sfx("ufo_zoom")
                if f % 2 == 0:
                    self.parts.emit(ux + 52, uy + 30, -2, 1, 20, TOXIC, size=1.0)
            ex, ey = self.ufo.draw(cv, int(ux), int(uy), f)
            # tractor beam
            if BEAM_ON <= f < ABSORB + 10:
                if f == BEAM_ON:
                    ctx.sfx("beam")
                beam_bot = star_y + 14
                for y in range(int(ey), int(beam_bot)):
                    k = (y - ey) / max(1, beam_bot - ey)
                    half = 4 + k * 14
                    for x in range(int(ex - half), int(ex + half)):
                        if (x + y + f // 2) % 2 == 0 and 0 <= x < W and 0 <= y < H:
                            c = cv.px[y, x].astype(int)
                            cv.px[y, x] = np.minimum(255, c + np.array([60, 140, 40]))
                    cv.pset(ex - half, y, LIME)
                    cv.pset(ex + half, y, LIME)
                for r in range(3):
                    yy = ey + ((f * 1.2 + r * 12) % (beam_bot - ey))
                    k = (yy - ey) / max(1, beam_bot - ey)
                    half = 4 + k * 14
                    cv.rect(ex - half, yy, half * 2, 1, (200, 255, 150))
            # the star rising into the UFO
            if BEAM_ON + 24 <= f < ABSORB:
                k = ease_in_out((f - BEAM_ON - 24) / (ABSORB - BEAM_ON - 24))
                sy = lerp(star_y, ey + 4, k)
                self.star.draw(cv, tx, sy, f * 2, scale=1 - 0.6 * k, rays=True, glow=1 - k)
                if f % 2 == 0:
                    self.parts.emit(tx + rng.normal(0, 4), sy + 8, 0, -1.2, 20, GOLDEN)
            if f == ABSORB:
                ctx.sfx("powerdown")
                self.shake = 4
                self.parts.burst(rng, ex, ey, 50, 3, 30, GOLDEN, drag=0.05)

    def draw_ship(self, cv, f):
        rng, ctx = self.rng, self.ctx
        if f < SHIP_IN:
            return
        if f == SHIP_IN:
            ctx.sfx("ship_arrive")
        if f == BOARD + 14:
            ctx.sfx("board")
        if f == IGNITE:
            ctx.sfx("ignite")
        if f == LAUNCH:
            ctx.sfx("launch")
            self.shake = 6
        sx, sy = self.ship_pos(f)
        flame = 4 + (f % 3) * 2
        if f >= IGNITE:
            flame = 8 + (f % 3) * 3 + (10 if f >= LAUNCH else 0)
            self.shake = max(self.shake, 1.5)
            for j in range(3):
                self.parts.emit(sx + 2, sy + 7 + rng.normal(0, 1.5), -2.5 - rng.random() * 2,
                                rng.normal(0.5, 0.4), 24, FIRE, size=1.0)
                self.parts.emit(sx, sy + 8, -1.0 - rng.random(), rng.normal(0.8, 0.5), 50, SMOKE,
                                size=3.0, drag=0.03)
        for k in range(flame):
            c = WHITE if k < 2 else CYAN if k < flame * 0.5 else SKY
            cv.rect(sx - k, sy + 6 + (k % 2), 1, 2 - (k > flame * 0.7), c)
        cv.blit(PLAYER_SHIP, sx, sy)
