"""Ending: the Star Core returns, Neon City lights up again, fireworks on the
beat, thank-you credits, and the arcade tube switches off."""
import math

import numpy as np

from ..engine import W, H, Particles, clamp, ease_in_out, ease_out_back, ease_out_cubic, lerp
from ..hero import Hero
from ..logo import logo_letter
from ..palette import (AMBER, CYAN, GOLDEN, ICE, INK, LEMON, MAGENTA, NEON_PINK, ORANGE, PINK, PLASMA, RAINBOW,
                       RED, ROSE, SKY, TOXIC, VIOLET, WHITE, YELLOW, BLUE, ORCHID, CRIMSON, COBALT, NAVY)
from ..props import StarCore
from ..scene import Scene
from ..sprites import PLAYER_SHIP
from .city import CAM_END, TOWER_TOP, City, hero_x, RUN_END

B = 24
STAR_HOME = 4 * B          # star settles on the tower
LIGHTS = STAR_HOME
HERO_OUT = 7 * B + 12
FW_START = 8 * B
MSG1 = 9 * B
THANKS = 16 * B
THE_END = 24 * B
CRT_OFF = 34 * B           # scene is 9 bars = 36 beats; the tube switches off over the last 2 beats

FW_RAMPS = [NEON_PINK, PLASMA, GOLDEN, TOXIC, [WHITE, ROSE, RED, CRIMSON, (90, 20, 50)],
            [WHITE, ICE, SKY, BLUE, COBALT, NAVY], [WHITE, LEMON, ORCHID, VIOLET, (60, 30, 100)]]


class Ending(Scene):
    def __init__(self, ctx, n):
        super().__init__(ctx, n)
        self.city = City(ctx, 0)
        self.city.lights_on = 0.0
        self.city.backdrop_hook = self._backdrop_hook
        self.star = StarCore()
        self.hero = Hero()
        self.parts = Particles(9000)
        self.shells = []
        self.hero_x = hero_x(RUN_END + 60) - CAM_END
        self.thanks = None
        self.fw_plan = self._plan_fireworks()
        self.flashes = []

    def _plan_fireworks(self):
        rng = np.random.default_rng(7)
        plan = []
        beat = 8
        kinds = ["ring", "sphere", "double", "heart", "willow", "sphere", "ring", "double"]
        i = 0
        while beat < 33:
            n = 3 if beat in (16, 24, 32) else 2 if beat >= 26 and beat % 2 == 0 else 1
            for k in range(n):
                side = (i + k) % 3
                x = [rng.uniform(26, 120), rng.uniform(120, 230), rng.uniform(230, 360)][side]
                plan.append({"f": int(beat * B) - 30, "x": float(x), "y": float(rng.uniform(24, 76)),
                             "ramp": FW_RAMPS[int(rng.integers(0, len(FW_RAMPS)))],
                             "kind": kinds[(i + k) % len(kinds)]})
            i += n
            beat += 2 if beat < 20 else 1
        return plan

    # the returned Star Core on top of the tower
    def _backdrop_hook(self, cv, f, tx):
        self._tx = tx
        sy = TOWER_TOP - 12
        if self._f >= STAR_HOME:
            self.star.draw(cv, tx, sy, self._f, glow=1.2)

    def star_path(self, f, tx):
        """Star carried by the ship, then floating down onto the tower."""
        sy_home = TOWER_TOP - 12
        if f < 2 * B:
            k = ease_out_cubic(f / (2 * B))
            return lerp(W + 30, tx + 30, k), lerp(-30, 40, k)
        k = ease_in_out((f - 2 * B) / (STAR_HOME - 2 * B))
        return lerp(tx + 30, tx, k), lerp(40, sy_home, k)

    def ship_pos(self, f):
        if f < 2 * B:
            k = ease_out_cubic(f / (2 * B))
            return lerp(W + 10, 316, k), lerp(-40, 28, k)
        if f < HERO_OUT:
            k = ease_in_out((f - 2 * B) / (HERO_OUT - 2 * B))
            return lerp(316, self.hero_x + 30, k), lerp(28, 150, k) - math.sin(k * math.pi) * 20
        return self.hero_x + 30, 150 + math.sin(f * 0.08) * 1.5

    def launch(self, fw):
        self.shells.append({"x": fw["x"] + (fw["x"] - 140) * 0.2, "y": H + 4, "tx": fw["x"], "ty": fw["y"],
                            "f0": self._f, "fw": fw})
        self.ctx.sfx("fw_launch", pan=clamp(fw["x"] / W * 2 - 1, -1, 1))

    def burst(self, fw, x, y):
        rng = self.rng
        kind = fw["kind"]
        ramp = fw["ramp"]
        if kind == "ring":
            for sp, n, r in ((2.8, 72, ramp), (1.5, 36, [WHITE, LEMON, YELLOW, AMBER, ORANGE])):
                a = np.arange(n) * (2 * math.pi / n) + rng.random()
                self.parts.emit(x, y, np.cos(a) * sp, np.sin(a) * sp, 62, r, grav=0.022, drag=0.022)
        elif kind == "double":
            for sp, r in ((3.0, ramp), (1.9, FW_RAMPS[(FW_RAMPS.index(ramp) + 3) % len(FW_RAMPS)])):
                n = 60
                a = np.arange(n) * (2 * math.pi / n) + sp
                self.parts.emit(x, y, np.cos(a) * sp, np.sin(a) * sp, 60, r, grav=0.022, drag=0.022)
        elif kind == "heart":
            t = np.linspace(0, 2 * math.pi, 80, endpoint=False)
            hx = 16 * np.sin(t) ** 3
            hy = -(13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t))
            self.parts.emit(x, y, hx * 0.17, hy * 0.17, 64, [WHITE, ROSE, PINK, MAGENTA, CRIMSON],
                            grav=0.01, drag=0.028)
        elif kind == "willow":
            self.parts.burst(rng, x, y, 120, 2.4, 100, GOLDEN, grav=0.03, drag=0.03, speed_jitter=0.3)
        else:
            self.parts.burst(rng, x, y, 140, 3.0, 58, ramp, grav=0.022, drag=0.028, speed_jitter=0.7)
            self.parts.burst(rng, x, y, 20, 1.2, 70, [WHITE, LEMON, AMBER], grav=0.02, drag=0.03, size=1.2)
        self.parts.burst(rng, x, y, 18, 0.9, 30, [WHITE, LEMON, AMBER], drag=0.05)
        self.flashes.append((x, y, self._f))
        self.ctx.sfx("fw_burst", pan=clamp(x / W * 2 - 1, -1, 1))

    def render(self, f):
        self._f = f
        cv, ctx, rng = self.cv, self.ctx, self.rng
        city = self.city
        cam = CAM_END
        # lights come back on in a sweep outward from the tower
        if f < LIGHTS:
            city.lights_on = 0.0
            city.draw_backdrop(cv, f, cam, theft=False)
            city.draw_foreground(cv, f, cam)
        elif f < LIGHTS + 40:
            k = (f - LIGHTS) / 40
            city.lights_on = 0.0
            city.draw_backdrop(cv, f, cam, theft=False)
            city.draw_foreground(cv, f, cam)
            dark = cv.px.copy()
            city.lights_on = 1.0
            city.draw_backdrop(cv, f, cam, theft=False)
            city.draw_foreground(cv, f, cam)
            tx = getattr(self, "_tx", 290)
            xx = np.abs(np.arange(W) - tx)[None, :]
            yy = np.arange(H)[:, None]
            m = (xx + (H - yy) * 0.3) > k * 420
            cv.px[np.broadcast_to(m, (H, W))] = dark[np.broadcast_to(m, (H, W))]
        else:
            city.lights_on = 1.0
            city.draw_backdrop(cv, f, cam, theft=False)
            city.draw_foreground(cv, f, cam)
        if f == LIGHTS:
            ctx.sfx("lights_on")
            tx = getattr(self, "_tx", 290)
            self.parts.burst(rng, tx, TOWER_TOP - 12, 80, 3.0, 40, GOLDEN, drag=0.04)
            self.flashes.append((tx, TOWER_TOP - 12, f))
        if f == 2 * B:
            ctx.sfx("star_release")

        # fireworks
        for fw in self.fw_plan:
            if fw["f"] == f:
                self.launch(fw)
        alive = []
        for s in self.shells:
            k = (f - s["f0"]) / 30
            if k >= 1:
                self.burst(s["fw"], s["tx"], s["ty"])
                continue
            x = lerp(s["x"], s["tx"], k)
            y = lerp(s["y"], s["ty"], 1 - (1 - k) ** 2)
            cv.pset(x, y, WHITE)
            self.parts.emit(x, y, rng.normal(0, 0.15), 0.4, 14, GOLDEN)
            alive.append(s)
        self.shells = alive

        # the star being brought home + the ship
        tx = getattr(self, "_tx", 290)
        if f < STAR_HOME:
            sx, sy = self.star_path(f, tx)
            self.star.draw(cv, sx, sy, f, scale=1.0, glow=0.8)
            if f % 2 == 0:
                self.parts.emit(sx, sy, rng.normal(0, 0.4), rng.normal(0, 0.4), 20, GOLDEN)
        shx, shy = self.ship_pos(f)
        flame = 4 + (f % 3) * 2
        for k in range(flame):
            cv.rect(shx - k, shy + 6 + (k % 2), 1, 2, WHITE if k < 2 else CYAN)
        cv.blit(PLAYER_SHIP, shx, shy)

        # hero hops out and celebrates
        if f >= HERO_OUT:
            k = clamp((f - HERO_OUT) / 18)
            hx = lerp(shx + 8, self.hero_x, k)
            hy = lerp(shy + 4, 176, k) - 26 * 4 * k * (1 - k)
            if k < 1:
                pose = "jump" if k < 0.5 else "fall"
                arm = None
            else:
                # jump for joy on every other beat, wave in between
                ph = (f - HERO_OUT - 18) % (2 * B)
                if ph < 18 and f > HERO_OUT + 40:
                    j = ph / 18
                    hy = 176 - 22 * 4 * j * (1 - j)
                    pose = "jump" if j < 0.5 else "fall"
                    arm = "torso_up"
                else:
                    pose = "stand"
                    arm = "torso_up" if (f // 12) % 2 == 0 else "torso_fwd"
            self.hero.draw(cv, hx, hy, pose=pose, frame=f, vx=1.5, vy=0.0, arm=arm)
            if f == HERO_OUT + 18:
                ctx.sfx("land")

        self.parts.update()
        self.parts.draw(cv)
        alive = []
        for (x, y, f0) in self.flashes:
            dt = f - f0
            if dt < 5:
                cv.circle(x, y, 9 - dt * 1.8, WHITE)
                alive.append((x, y, f0))
        self.flashes = alive

        # messages
        if MSG1 <= f < THANKS:
            lines = ["THE STAR CORE IS SAFE!", "NEON CITY SHINES AGAIN"]
            for i, line in enumerate(lines):
                t0 = MSG1 + i * 2 * B
                if f >= t0:
                    n = min(len(line), (f - t0) // 2 + 1)
                    if n < len(line) and (f - t0) % 4 == 0 and line[n - 1] != " ":
                        ctx.sfx("blip")
                    cv.text(line[:n], W // 2 - len(line) * 3, 40 + i * 14, WHITE if i == 0 else YELLOW,
                            outline=INK, shadow=INK)
        if f >= THANKS:
            if self.thanks is None:
                word = "THANK YOU"
                grad = [WHITE, ICE, CYAN, SKY, BLUE, COBALT, COBALT]
                self.thanks = [logo_letter(ch, 3, grad, [NAVY, (16, 20, 70)], depth=3) if ch != " " else None
                               for ch in word]
            pitch = 18
            word = "THANK YOU"
            x0 = W // 2 - (len(word) * pitch) // 2
            for i, spr in enumerate(self.thanks):
                if spr is None:
                    continue
                land = THANKS + i * 4
                k = clamp((f - land + 8) / 8)
                if k <= 0:
                    continue
                y = lerp(-30, 26, ease_out_back(k)) + math.sin((f + i * 6) * 0.1) * 1.5
                cv.blit(spr, x0 + i * pitch, y)
                if f == land:
                    ctx.sfx("letter", pitch=i)
            if f >= THANKS + B:
                cv.text("FOR PLAYING!", W // 2, 58, YELLOW, scale=2, outline=INK, shadow=CRIMSON, align="center")
        if f >= THE_END:
            k = clamp((f - THE_END) / 30)
            if k > 0:
                cv.text("THE END", W // 2, 88, RAINBOW[(f // 6) % len(RAINBOW)] if f > THE_END + 30 else WHITE,
                        scale=2, outline=INK, shadow=INK, align="center")
            cv.text(f"FINAL SCORE {int(ctx.score):07d}", W // 2, 108, WHITE, outline=INK, align="center")
            if f >= THE_END + 4 * B and (f // 20) % 2 == 0:
                cv.text("INSERT COIN TO PLAY AGAIN", W // 2, 124, CYAN, outline=INK, align="center")
            if f == THE_END:
                ctx.sfx("the_end")

        # opening fade from the white flash of the previous scene
        if f < 12:
            cv.flash(1 - f / 12)
        post = {"bloom": 1.1}
        if f >= CRT_OFF:
            post["crt"] = ("off", clamp((f - CRT_OFF) / (2 * B - 6)))
        if f == CRT_OFF:
            ctx.sfx("crt_off")
        return cv, post
