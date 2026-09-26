"""Title screen: synthwave sunset, comet streak, logo slam, hero pose."""
import math

import numpy as np

from ..backgrounds import HORIZON, Synthwave
from ..engine import (W, H, Particles, ease_in_cubic, ease_out_cubic, shake_offset, shift_canvas, star_glint)
from ..hero import Hero, draw_hero_scaled
from ..logo import logo_letter
from ..palette import (AMBER, BLUE, COBALT, CRIMSON, CYAN, GOLDEN, ICE, INK, LEMON, NAVY, ORANGE, PLASMA, SCARLET,
                       SKY, SMOKE, WHITE, YELLOW)
from ..scene import Scene, beats, stripe_wipe

HOT = [LEMON, YELLOW, YELLOW, AMBER, ORANGE, ORANGE, SCARLET]
COOL = [ICE, ICE, CYAN, CYAN, SKY, BLUE, COBALT]
LOGO_Y = 20
SCALE = 5


class Title(Scene):
    def __init__(self, ctx, n):
        super().__init__(ctx, n)
        self.bg = Synthwave(self.rng)
        self.parts = Particles(4000)
        self.hero = Hero()
        word = "COMET KID"
        self.letters = []
        pitch = 6 * SCALE
        total = len(word) * pitch - SCALE
        x0 = (W - total) // 2
        for i, ch in enumerate(word):
            if ch == " ":
                continue
            hot = i < 5
            spr = logo_letter(ch, SCALE, HOT if hot else COOL,
                              [CRIMSON, (140, 16, 60), (90, 10, 50)] if hot else [COBALT, NAVY, (16, 20, 70)],
                              depth=5)
            land = beats(1) + i * 12 if hot else beats(4)
            self.letters.append({"spr": spr, "x": x0 + i * pitch - 2, "land": land, "hot": hot})
        self.shake = 0.0
        self.sub = "- QUEST FOR THE STAR CORE -"

    def comet_pos(self, f):
        k = f / 46.0
        return -30 + k * 460, 8 + k * 58

    def render(self, f):
        cv, ctx, rng = self.cv, self.ctx, self.rng
        bg = self.bg
        bg.draw_sky(cv, f)
        bg.draw_sun(cv, f, cy=HORIZON - 8)
        bg.draw_mountains(cv, f)
        bg.draw_floor(cv, f, speed=1.0)

        # comet streak across the sky at the start
        if f < 46:
            cx, cy = self.comet_pos(f)
            for k in range(3):
                self.parts.emit(cx - k * 3, cy - k * 0.4, rng.normal(-0.6, 0.3), rng.normal(0, 0.25),
                                26 + rng.random() * 18, PLASMA)
            if f % 3 == 0:
                self.parts.emit(cx, cy, rng.normal(-1, 0.5), rng.normal(0, 0.5), 30, GOLDEN)
        if f == 0:
            ctx.sfx("comet")

        # logo letters
        for L in self.letters:
            land = L["land"]
            spr = L["spr"]
            if f < land - 8:
                continue
            if f < land:
                k = (f - (land - 8)) / 8
                y = LOGO_Y - 90 + 90 * ease_in_cubic(k)
            else:
                k = (f - land) / 14.0
                y = LOGO_Y - (math.sin(min(k, 1) * math.pi) * 5 * (1 - min(k, 1))) if k < 1 else LOGO_Y
                y += math.sin((f + L["x"]) * 0.06) * 1.2 if f > beats(6) else 0
            if f == land:
                big = not L["hot"]
                ctx.sfx("slam" if big else "thud", pan=(L["x"] / W) * 2 - 1)
                self.shake = max(self.shake, 5.0 if big else 2.5)
                bx = L["x"] + spr.w / 2
                by = LOGO_Y + spr.h
                self.parts.burst(rng, bx, by, 16 if not big else 40, 1.6 if not big else 3.0, 24, SMOKE,
                                 spread=math.pi, angle=-math.pi / 2, size=1.5, drag=0.08)
                if big:
                    self.parts.burst(rng, bx, LOGO_Y + 18, 50, 3.5, 30, PLASMA, drag=0.05)
            cv.blit(spr, L["x"], int(round(y)))

        # shine sweep across the logo
        period = beats(8)
        if f > beats(5):
            ph = (f - beats(5)) % period
            if ph < 40:
                sx = -40 + ph * 11
                for L in self.letters:
                    spr = L["spr"]
                    lx = L["x"]
                    ly = LOGO_Y + int(round(math.sin((f + lx) * 0.06) * 1.2 if f > beats(6) else 0))
                    yy, xx = np.nonzero(spr.face)
                    gx = xx + lx + (yy + ly) * 0.5
                    sel = (gx > sx) & (gx < sx + 7)
                    for a, b in zip(yy[sel], xx[sel]):
                        cv.pset(lx + b, ly + a, WHITE)

        # subtitle typewriter
        t0 = beats(5)
        if f >= t0:
            nch = min(len(self.sub), (f - t0) // 2 + 1)
            s = self.sub[:nch]
            if nch < len(self.sub) and (f - t0) % 4 == 0 and s[-1] != " ":
                ctx.sfx("blip")
            w = len(self.sub) * 6 - 1
            cv.text(s, W // 2 - w // 2, 76, WHITE, shadow=INK, outline=(90, 20, 90))

        # hero runs in and poses
        hx_target = 58
        run_in = beats(8)
        stop = beats(10)
        dash = beats(21)
        if f >= run_in:
            if f < stop:
                k = (f - run_in) / (stop - run_in)
                hx = -40 + (hx_target + 40) * ease_out_cubic(k)
                vx = (hx_target + 40) * 3 * (1 - k) ** 2 / (stop - run_in) / 2
                pose = "run" if vx > 0.5 else "stand"
                if k > 0.7 and f % 2 == 0:
                    self.parts.emit(hx + 20, 206, rng.normal(-0.8, 0.4), rng.normal(-0.5, 0.2), 20, SMOKE,
                                    size=2.0)
            elif f < dash:
                hx, vx = hx_target, 0.0
                pose = "stand"
            else:
                k = (f - dash) / 24.0
                hx = hx_target + 420 * ease_in_cubic(min(k, 1))
                vx = 3.0
                pose = "run"
                if hx < W:
                    for j in range(2):
                        self.parts.emit(hx + 12, 170 + rng.random() * 30, -2.0 - rng.random(), 0, 20, PLASMA,
                                        size=1.5)
            if f == stop:
                ctx.sfx("skid")
            if f == dash:
                ctx.sfx("dash")
            wind_vx = max(vx, 2.2)
            arm = "torso_up" if beats(11) <= f < dash and ((f - beats(11)) // beats(2)) % 4 == 0 else None
            if hx < W + 40:
                draw_hero_scaled(self.hero, cv, hx, 208, 2, pose=pose, frame=f, vx=wind_vx, arm=arm)

        # PUSH START
        press = beats(20)
        if beats(12) <= f < press:
            if (f // 20) % 2 == 0:
                cv.text("PUSH START", W // 2, 172, YELLOW, scale=2, outline=INK, shadow=CRIMSON, align="center")
        elif press <= f < press + 30:
            if (f // 3) % 2 == 0:
                cv.text("PUSH START", W // 2, 172, WHITE, scale=2, outline=INK, shadow=CYAN, align="center")
        if f == press:
            ctx.sfx("start")
        cv.text("CREDIT 01", W - 8, H - 10, WHITE, align="right")
        cv.text("(C)2026 COMET KID TEAM", 8, H - 10, (200, 150, 220))

        self.parts.update()
        self.parts.draw(cv)
        if f < 46:
            cx, cy = self.comet_pos(f)
            cv.circle(cx, cy, 3, ICE)
            cv.circle(cx, cy, 1.5, WHITE)
            star_glint(cv, cx, cy, 6, CYAN)

        # screen shake
        if self.shake > 0.3:
            dx, dy = shake_offset(rng, self.shake)
            shift_canvas(cv, dx, dy)
        self.shake *= 0.82

        # opening flash (from the boot screen) and the exit wipe
        if f < 10:
            cv.flash(1 - f / 10)
        if f >= self.n - 24:
            stripe_wipe(cv, (f - (self.n - 24)) / 22)
        if f == self.n - 24:
            ctx.sfx("wipe")
        post = {"bloom": 1.0}
        return cv, post
