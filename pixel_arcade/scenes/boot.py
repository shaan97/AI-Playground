"""Arcade cabinet boot: CRT warms up, INSERT COIN, a coin drops in."""
import math

from ..backgrounds import Starfield
from ..engine import W, H, Particles, dither_gradient, ease_in_cubic, star_glint
from ..palette import (CYAN, DEEP, GOLDEN, GREY, INK, NIGHT, RED, SILVER, SLATE, STEEL, WHITE, YELLOW, NAVY,
                       PLASMA)
from ..scene import Scene, beats
from ..sprites import COIN

COIN_DROP = beats(4)      # coin starts falling
COIN_IN = beats(6)        # coin enters the slot (on the beat)


class Boot(Scene):
    def __init__(self, ctx, n):
        super().__init__(ctx, n)
        self.bg = dither_gradient(H, W, [INK, NIGHT, NIGHT, DEEP, (40, 26, 84)])
        self.stars = Starfield(self.rng, 140)
        self.parts = Particles(2000)
        self.coin = [c.scaled(3) for c in COIN]
        self.credit = 0

    def render(self, f):
        cv, ctx = self.cv, self.ctx
        cv.px[:] = self.bg
        self.stars.draw(cv, f, vx=0.0, vy=0.35)
        if f == 4:
            ctx.sfx("crt_on")
        # top line
        cv.text("1UP", 8, 4, RED, shadow=INK)
        cv.text("0000000", 8, 13, WHITE)
        cv.text("HI-SCORE", W // 2, 4, RED, align="center")
        cv.text(f"{ctx.hiscore:07d}", W // 2, 13, WHITE, align="center")
        cv.text("2UP", W - 8, 4, RED, align="right")

        # coin slot panel
        sx, sy = W // 2, 150
        cv.rect(sx - 22, sy - 16, 44, 40, INK)
        cv.rect(sx - 21, sy - 15, 42, 38, SLATE)
        cv.rect(sx - 21, sy - 15, 42, 1, STEEL)
        cv.rect(sx - 20, sy - 14, 40, 36, (44, 50, 86))
        glow = 1.0 if f >= COIN_IN and (f // 4) % 2 == 0 and f < COIN_IN + 40 else 0.0
        cv.rect(sx - 12, sy - 8, 24, 20, INK)
        cv.rect(sx - 11, sy - 7, 22, 18, YELLOW if glow else (120, 30, 40))
        cv.text("25", sx - 1, sy - 3, INK if glow else (255, 120, 120), shadow=None, align="center")
        cv.rect(sx - 1, sy + 7, 2, 10, INK)
        cv.rect(sx - 1, sy + 8, 2, 1, (255, 230, 150) if glow else GREY)

        if f < COIN_IN:
            if (f // 24) % 2 == 0 or f >= COIN_DROP:
                cv.text("INSERT COIN", W // 2, 92, YELLOW, scale=2, shadow=RED, align="center")
        else:
            if (f // 6) % 2 == 0:
                cv.text("PUSH START", W // 2, 92, CYAN, scale=2, shadow=NAVY, align="center")

        # the coin
        if COIN_DROP <= f < COIN_IN:
            k = (f - COIN_DROP) / (COIN_IN - COIN_DROP)
            y = -30 + (sy + 2 - (-30)) * ease_in_cubic(k)
            x = sx - 12 + math.sin(k * 3.0) * 3 * (1 - k)
            fr = self.coin[(f // 3) % 4]
            cv.blit(fr, x + (24 - fr.w) // 2, y - 12)
            if f % 2 == 0:
                self.parts.emit(x + 12, y - 12, self.rng.normal(0, 0.3), -0.5, 16, GOLDEN)
        if f == COIN_IN:
            ctx.sfx("coin_insert")
            self.credit = 1
            self.parts.burst(self.rng, sx, sy + 8, 60, 2.8, 30, GOLDEN, drag=0.06)
            self.parts.burst(self.rng, sx, sy + 8, 20, 1.5, 40, PLASMA, drag=0.04)
        self.parts.update()
        self.parts.draw(cv)
        if COIN_IN <= f < COIN_IN + 30:
            k = (f - COIN_IN) / 30
            star_glint(cv, sx - 26, sy - 10 - k * 10, 3 - int(k * 3), YELLOW)
            star_glint(cv, sx + 26, sy - 6 - k * 12, 3 - int(k * 3), CYAN)

        cv.text(f"CREDIT {self.credit:02d}", W - 8, H - 12, WHITE if self.credit else GREY, align="right")
        cv.text("1 COIN 1 PLAY", 8, H - 12, SILVER)

        post = {"bloom": 0.9}
        if f < 44:
            post["crt"] = ("on", max(0.0, (f - 4) / 40))
        if f >= self.n - 8:
            cv.flash((f - (self.n - 8)) / 8)
        if f == self.n - 12:
            ctx.sfx("whoosh")
        return cv, post
