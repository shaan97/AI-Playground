"""Scene framework: shared context (score, sound events) and HUD helpers."""
import zlib

import numpy as np

from .engine import FRAMES_PER_BAR, FRAMES_PER_BEAT, W, Canvas
from .palette import CYAN, INK, RED, WHITE, YELLOW
from .sprites import HEART, MINI_SHIP


class Context:
    """State shared across the whole video."""

    def __init__(self):
        self.events = []        # (global_frame, name, params)
        self.frame = 0
        self.score = 0
        self.shown_score = 0.0  # animated roll-up value
        self.hiscore = 220000   # beaten during the final bonus tally
        self.lives = 3

    def sfx(self, name, delay=0, **kw):
        self.events.append((self.frame + delay, name, kw))

    def add_score(self, pts):
        self.score += pts

    def tick_score(self):
        if self.shown_score < self.score:
            self.shown_score = min(self.score, self.shown_score + max(10, (self.score - self.shown_score) * 0.18))


class Scene:
    def __init__(self, ctx, n_frames):
        self.ctx = ctx
        self.n = n_frames
        self.cv = Canvas()
        # stable per-scene seed (str hash() is randomized per process)
        self.rng = np.random.default_rng(zlib.crc32(type(self).__name__.encode()))

    def render(self, f):
        """Return (canvas, post-params dict)."""
        raise NotImplementedError


def beats(b):
    return int(round(b * FRAMES_PER_BEAT))


def bars(b):
    return int(round(b * FRAMES_PER_BAR))


def draw_hud(cv, ctx, lives_icon="heart", t=0):
    ctx.tick_score()
    s = int(ctx.shown_score)
    hi = max(ctx.hiscore, s)
    cv.text("1UP", 8, 4, RED if (t // 30) % 2 == 0 else WHITE, shadow=INK)
    cv.text(f"{s:07d}", 8, 13, WHITE, shadow=INK)
    cv.text("HI-SCORE", W // 2, 4, RED, shadow=INK, align="center")
    cv.text(f"{hi:07d}", W // 2, 13, YELLOW if s >= ctx.hiscore else WHITE, shadow=INK, align="center")
    icon = HEART if lives_icon == "heart" else MINI_SHIP
    for i in range(ctx.lives):
        cv.blit(icon, W - 12 - i * (icon.w + 3), 6)


def iris(cv, cx, cy, r, color=INK):
    """Blacken everything outside a circle of radius r (pixel-art iris wipe)."""
    yy, xx = np.ogrid[0:cv.h, 0:cv.w]
    m = (xx - cx) ** 2 + (yy - cy) ** 2 > r * r
    cv.px[m] = color


def stripe_wipe(cv, t, color=INK, n=12, reverse=False):
    """Diagonal band wipe. t 0..1 covers the screen."""
    if t <= 0:
        return
    yy, xx = np.ogrid[0:cv.h, 0:cv.w]
    band = cv.h // n + 1
    phase = (yy // band) % 2
    reach = (t * (cv.w + 120)) - phase * 40
    pos = xx + (yy % band) * 0.6
    if reverse:
        pos = cv.w - pos
    cv.px[pos < reach] = color


def card(cv, title, subtitle, t, y=84, col=YELLOW):
    """Stage title card sliding in/out; t in [0, 1] over its lifetime."""
    from .engine import ease_out_cubic, ease_in_cubic
    if t <= 0 or t >= 1:
        return
    if t < 0.2:
        k = ease_out_cubic(t / 0.2)
        off = (1 - k) * -W
    elif t > 0.8:
        k = ease_in_cubic((t - 0.8) / 0.2)
        off = k * W
    else:
        off = 0
    bw = 220
    x0 = W // 2 - bw // 2 + off
    cv.dither_rect(0, y - 6 + 0, W, 44, INK, 0.5)
    cv.rect(x0 - 40, y - 4, bw + 80, 40, INK)
    cv.rect(x0 - 40, y - 4, bw + 80, 1, CYAN)
    cv.rect(x0 - 40, y + 35, bw + 80, 1, CYAN)
    cv.text(title, W // 2 + off, y + 2, WHITE, scale=2, shadow=None, align="center")
    cv.text(subtitle, W // 2 + off, y + 20, col, scale=2, shadow=RED, align="center", shadow_off=(1, 1))
