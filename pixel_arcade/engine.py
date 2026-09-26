"""Low-resolution pixel canvas, sprites, text and dithering helpers.

Everything is drawn onto a 384x216 canvas (5x of which is 1920x1080), so the
final video has chunky, perfectly square pixels.
"""
import math

import numpy as np

from . import font
from .palette import INK, WHITE

W, H = 384, 216
FPS = 60
BPM = 150
FRAMES_PER_BEAT = FPS * 60 // BPM          # 24
FRAMES_PER_STEP = FRAMES_PER_BEAT // 4     # 6  (one 16th note)
FRAMES_PER_BAR = FRAMES_PER_BEAT * 4       # 96


# --------------------------------------------------------------------------
# math helpers
# --------------------------------------------------------------------------

def clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else hi if v > hi else v


def lerp(a, b, t):
    return a + (b - a) * t


def inv_lerp(a, b, v):
    if b == a:
        return 1.0
    return clamp((v - a) / (b - a))


def ease_out_cubic(t):
    t = clamp(t)
    return 1 - (1 - t) ** 3


def ease_in_cubic(t):
    t = clamp(t)
    return t * t * t


def ease_in_out(t):
    t = clamp(t)
    return t * t * (3 - 2 * t)


def ease_out_back(t, s=1.9):
    t = clamp(t) - 1
    return t * t * ((s + 1) * t + s) + 1


def ease_out_bounce(t):
    t = clamp(t)
    n1, d1 = 7.5625, 2.75
    if t < 1 / d1:
        return n1 * t * t
    if t < 2 / d1:
        t -= 1.5 / d1
        return n1 * t * t + 0.75
    if t < 2.5 / d1:
        t -= 2.25 / d1
        return n1 * t * t + 0.9375
    t -= 2.625 / d1
    return n1 * t * t + 0.984375


def ease_out_elastic(t):
    t = clamp(t)
    if t in (0.0, 1.0):
        return t
    return 2 ** (-10 * t) * math.sin((t * 10 - 0.75) * (2 * math.pi / 3)) + 1


# --------------------------------------------------------------------------
# dithering
# --------------------------------------------------------------------------

_B4 = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], dtype=np.float32)
BAYER4 = (_B4 + 0.5) / 16.0
BAYER = np.tile(BAYER4, (H // 4 + 2, W // 4 + 2))  # screen-sized threshold map (+margin)


def bayer(h, w, ox=0, oy=0):
    """Ordered-dither threshold map of any size, offset by (ox, oy)."""
    ox %= 4
    oy %= 4
    t = np.tile(BAYER4, (h // 4 + 2, w // 4 + 2))
    return t[oy:oy + h, ox:ox + w]


def dither_gradient(h, w, stops, ox=0, oy=0):
    """Vertical ordered-dither gradient through a list of colors -> (h, w, 3)."""
    stops = np.array(stops, dtype=np.float32)
    n = len(stops) - 1
    t = np.broadcast_to(np.linspace(0, n, h, endpoint=False, dtype=np.float32)[:, None], (h, w))
    i = np.clip(np.floor(t).astype(int), 0, n - 1)
    f = t - i
    pick = np.clip(np.where(f > bayer(h, w, ox, oy), i + 1, i), 0, n)
    return stops[pick].astype(np.uint8)


# --------------------------------------------------------------------------
# sprites
# --------------------------------------------------------------------------

class Sprite:
    """RGB pixels + opacity mask. Built from ASCII art or numpy arrays."""

    def __init__(self, rgb, mask):
        self.rgb = rgb
        self.mask = mask
        self.h, self.w = mask.shape
        self._flip = None
        self._solid = {}

    @classmethod
    def from_ascii(cls, rows, key):
        rows = [r for r in rows]
        h = len(rows)
        w = max(len(r) for r in rows)
        rgb = np.zeros((h, w, 3), np.uint8)
        mask = np.zeros((h, w), bool)
        for y, row in enumerate(rows):
            for x, ch in enumerate(row):
                if ch in (".", " "):
                    continue
                if ch not in key:
                    raise KeyError(f"sprite char {ch!r} missing from key")
                rgb[y, x] = key[ch]
                mask[y, x] = True
        return cls(rgb, mask)

    @classmethod
    def from_rgba(cls, rgba):
        return cls(np.ascontiguousarray(rgba[..., :3]), rgba[..., 3] > 127)

    def flipped(self):
        if self._flip is None:
            self._flip = Sprite(self.rgb[:, ::-1].copy(), self.mask[:, ::-1].copy())
            self._flip._flip = self
        return self._flip

    def flipped_v(self):
        return Sprite(self.rgb[::-1].copy(), self.mask[::-1].copy())

    def recolor(self, mapping):
        rgb = self.rgb.copy()
        for src, dst in mapping.items():
            sel = np.all(self.rgb == np.array(src, np.uint8), axis=-1) & self.mask
            rgb[sel] = dst
        return Sprite(rgb, self.mask.copy())

    def outlined(self, color=INK):
        """Return a copy with a 1px (orthogonal) outline around the opaque area."""
        h, w = self.mask.shape
        m = np.zeros((h + 2, w + 2), bool)
        for dy, dx in ((0, 1), (2, 1), (1, 0), (1, 2), (1, 1)):
            m[dy:dy + h, dx:dx + w] |= self.mask
        rgb = np.zeros((h + 2, w + 2, 3), np.uint8)
        rgb[m] = color
        rgb[1:1 + h, 1:1 + w][self.mask] = self.rgb[self.mask]
        return Sprite(rgb, m)

    def scaled(self, k):
        return Sprite(np.repeat(np.repeat(self.rgb, k, 0), k, 1), np.repeat(np.repeat(self.mask, k, 0), k, 1))


def sheet(frames_ascii, key):
    return [Sprite.from_ascii(f, key) for f in frames_ascii]


_disc_cache = {}


def disc_mask(r):
    r = int(r)
    m = _disc_cache.get(r)
    if m is None:
        yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
        m = xx * xx + yy * yy <= r * r + r * 0.8
        _disc_cache[r] = m
    return m


_ring_cache = {}


def ring_mask(r, t=1):
    key = (int(r), int(t))
    m = _ring_cache.get(key)
    if m is None:
        r = int(r)
        outer = disc_mask(r)
        if r - t >= 0:
            inner = np.zeros_like(outer)
            ri = r - t
            d = disc_mask(ri)
            inner[t:t + d.shape[0], t:t + d.shape[1]] = d
            m = outer & ~inner
        else:
            m = outer
        _ring_cache[key] = m
    return m


# --------------------------------------------------------------------------
# canvas
# --------------------------------------------------------------------------

class Canvas:
    def __init__(self, w=W, h=H):
        self.w, self.h = w, h
        self.px = np.zeros((h, w, 3), np.uint8)

    # -- basic -------------------------------------------------------------
    def clear(self, c=INK):
        self.px[:] = c

    def _clip(self, x, y, w, h):
        return max(0, x), max(0, y), min(self.w, x + w), min(self.h, y + h)

    def pset(self, x, y, c):
        x, y = int(math.floor(x)), int(math.floor(y))
        if 0 <= x < self.w and 0 <= y < self.h:
            self.px[y, x] = c

    def rect(self, x, y, w, h, c):
        x, y, w, h = int(math.floor(x)), int(math.floor(y)), int(w), int(h)
        x0, y0, x1, y1 = self._clip(x, y, w, h)
        if x1 > x0 and y1 > y0:
            self.px[y0:y1, x0:x1] = c

    def rect_outline(self, x, y, w, h, c):
        self.rect(x, y, w, 1, c)
        self.rect(x, y + h - 1, w, 1, c)
        self.rect(x, y, 1, h, c)
        self.rect(x + w - 1, y, 1, h, c)

    def line(self, x0, y0, x1, y1, c):
        n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
        xs = np.floor(np.linspace(x0, x1, n) + 0.5).astype(int)
        ys = np.floor(np.linspace(y0, y1, n) + 0.5).astype(int)
        ok = (xs >= 0) & (xs < self.w) & (ys >= 0) & (ys < self.h)
        self.px[ys[ok], xs[ok]] = c

    def thick_line(self, x0, y0, x1, y1, r, c):
        n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
        for i in range(0, n, max(1, int(r))):
            t = i / max(1, n - 1)
            self.circle(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, r, c)
        self.circle(x1, y1, r, c)

    def mask_fill(self, m, x, y, c):
        x, y = int(math.floor(x)), int(math.floor(y))
        mh, mw = m.shape
        x0, y0, x1, y1 = self._clip(x, y, mw, mh)
        if x1 <= x0 or y1 <= y0:
            return
        sub = m[y0 - y:y1 - y, x0 - x:x1 - x]
        self.px[y0:y1, x0:x1][sub] = c

    def mask_fill_rgb(self, m, rgb, x, y):
        """Fill mask with per-pixel colors taken from rgb (same shape as m)."""
        x, y = int(math.floor(x)), int(math.floor(y))
        mh, mw = m.shape
        x0, y0, x1, y1 = self._clip(x, y, mw, mh)
        if x1 <= x0 or y1 <= y0:
            return
        sub = m[y0 - y:y1 - y, x0 - x:x1 - x]
        self.px[y0:y1, x0:x1][sub] = rgb[y0 - y:y1 - y, x0 - x:x1 - x][sub]

    def circle(self, cx, cy, r, c):
        if r < 0.5:
            self.pset(cx, cy, c)
            return
        m = disc_mask(r)
        k = m.shape[0] // 2
        self.mask_fill(m, math.floor(cx) - k, math.floor(cy) - k, c)

    def ring(self, cx, cy, r, c, t=1):
        if r < 0.5:
            self.pset(cx, cy, c)
            return
        m = ring_mask(r, t)
        k = m.shape[0] // 2
        self.mask_fill(m, math.floor(cx) - k, math.floor(cy) - k, c)

    def blit(self, spr, x, y, flip=False, color=None, dither=None, tint=None):
        s = spr.flipped() if flip else spr
        x, y = int(math.floor(x)), int(math.floor(y))
        x0, y0, x1, y1 = self._clip(x, y, s.w, s.h)
        if x1 <= x0 or y1 <= y0:
            return
        sx, sy = x0 - x, y0 - y
        m = s.mask[sy:sy + y1 - y0, sx:sx + x1 - x0]
        if dither is not None:  # 0..1 opacity through ordered dithering
            m = m & (BAYER[y0:y1, x0:x1] < dither)
        dst = self.px[y0:y1, x0:x1]
        if color is not None:
            dst[m] = color
        elif tint is not None:
            tc, ta = tint
            src_px = s.rgb[sy:sy + y1 - y0, sx:sx + x1 - x0][m].astype(np.float32)
            dst[m] = (src_px * (1 - ta) + np.array(tc, np.float32) * ta).astype(np.uint8)
        else:
            dst[m] = s.rgb[sy:sy + y1 - y0, sx:sx + x1 - x0][m]

    def blit_centered(self, spr, cx, cy, **kw):
        self.blit(spr, cx - spr.w // 2, cy - spr.h // 2, **kw)

    def add_rgb(self, rgb, x, y):
        """Additive blend of an int/float (h,w,3) array (for glows)."""
        x, y = int(math.floor(x)), int(math.floor(y))
        h, w = rgb.shape[:2]
        x0, y0, x1, y1 = self._clip(x, y, w, h)
        if x1 <= x0 or y1 <= y0:
            return
        src = rgb[y0 - y:y1 - y, x0 - x:x1 - x]
        dst = self.px[y0:y1, x0:x1]
        dst[:] = np.clip(dst.astype(np.int16) + src.astype(np.int16), 0, 255).astype(np.uint8)

    def blend_rect(self, x, y, w, h, c, a):
        x, y = int(math.floor(x)), int(math.floor(y))
        x0, y0, x1, y1 = self._clip(x, y, int(w), int(h))
        if x1 <= x0 or y1 <= y0:
            return
        dst = self.px[y0:y1, x0:x1].astype(np.float32)
        dst += (np.array(c, np.float32) - dst) * a
        self.px[y0:y1, x0:x1] = dst.astype(np.uint8)

    def dither_rect(self, x, y, w, h, c, level):
        """Cover a rect with color c at ordered-dither density `level` (0..1)."""
        x, y = int(math.floor(x)), int(math.floor(y))
        x0, y0, x1, y1 = self._clip(x, y, int(w), int(h))
        if x1 <= x0 or y1 <= y0:
            return
        m = BAYER[y0:y1, x0:x1] < level
        self.px[y0:y1, x0:x1][m] = c

    def fade(self, level, c=INK):
        """Dithered fade of the whole screen toward c; level 0..1."""
        if level <= 0:
            return
        if level >= 1:
            self.px[:] = c
            return
        m = BAYER[:self.h, :self.w] < level
        self.px[m] = c

    def darken(self, f):
        self.px[:] = (self.px.astype(np.float32) * f).astype(np.uint8)

    def tint(self, c, a):
        self.px[:] = (self.px.astype(np.float32) * (1 - a) + np.array(c, np.float32) * a).astype(np.uint8)

    def flash(self, a, c=WHITE):
        if a > 0:
            self.tint(c, clamp(a))

    # -- text ----------------------------------------------------------------
    def text(self, s, x, y, c=WHITE, scale=1, shadow=INK, outline=None, align="left",
             gradient=None, spacing=1, shadow_off=(1, 1), ow=1):
        """Draw one line of text. Returns its pixel width."""
        m = font.text_mask(s, scale, spacing)
        h, w = m.shape
        if align == "center":
            x = x - w // 2
        elif align == "right":
            x = x - w
        x, y = int(x), int(y)
        if outline is not None:
            om = font.dilate(m, ow)
            if shadow is not None:
                self.mask_fill(om, x - ow + shadow_off[0], y - ow + shadow_off[1], shadow)
            self.mask_fill(om, x - ow, y - ow, outline)
        elif shadow is not None:
            self.mask_fill(m, x + shadow_off[0], y + shadow_off[1], shadow)
        if gradient is not None:
            stops = np.array(gradient, np.float32)
            n = len(stops)
            idx = np.clip((np.arange(h) * n) // h, 0, n - 1)
            rgb = np.repeat(stops[idx][:, None, :], w, axis=1).astype(np.uint8)
            self.mask_fill_rgb(m, rgb, x, y)
        else:
            self.mask_fill(m, x, y, c)
        return w


# --------------------------------------------------------------------------
# particles
# --------------------------------------------------------------------------

class Particles:
    """Vectorised particle system. Each particle walks down a color ramp."""

    def __init__(self, cap=6000):
        self.cap = cap
        self.n = 0
        z = lambda: np.zeros(cap, np.float32)
        self.x, self.y, self.vx, self.vy = z(), z(), z(), z()
        self.life, self.maxlife, self.grav, self.drag, self.size = z(), z(), z(), z(), z()
        self.ramp = np.zeros(cap, np.int32)
        self.ramps = []
        self._ramp_ids = {}

    def _ramp_id(self, ramp):
        key = tuple(ramp)
        if key not in self._ramp_ids:
            self._ramp_ids[key] = len(self.ramps)
            self.ramps.append(np.array(ramp, np.uint8))
        return self._ramp_ids[key]

    def emit(self, x, y, vx, vy, life, ramp, grav=0.0, drag=0.0, size=0.0):
        """Emit particles. Scalars or equal-length arrays are accepted."""
        vals = [np.atleast_1d(np.asarray(a, np.float32)) for a in (x, y, vx, vy, life, size)]
        k = min(max(len(a) for a in vals), self.cap - self.n)
        if k <= 0:
            return
        s = slice(self.n, self.n + k)
        for dst, a in zip((self.x, self.y, self.vx, self.vy, self.life, self.size), vals):
            dst[s] = a[:k] if len(a) > 1 else a[0]
        self.maxlife[s] = self.life[s]
        self.grav[s] = grav
        self.drag[s] = drag
        self.ramp[s] = self._ramp_id(ramp)
        self.n += k

    def burst(self, rng, x, y, n, speed, life, ramp, grav=0.0, drag=0.04, size=0.0, spread=math.tau, angle=0.0,
              speed_jitter=0.6, life_jitter=0.4, size_jitter=0.0):
        a = angle + (rng.random(n) - 0.5) * spread
        sp = speed * (1 - speed_jitter + speed_jitter * rng.random(n))
        lf = life * (1 - life_jitter + life_jitter * rng.random(n))
        sz = size + size_jitter * rng.random(n) if size_jitter else size
        self.emit(x, y, np.cos(a) * sp, np.sin(a) * sp, lf, ramp, grav, drag, sz)

    def shift(self, dx, dy=0.0):
        self.x[:self.n] += dx
        self.y[:self.n] += dy

    def update(self):
        n = self.n
        if n == 0:
            return
        self.vy[:n] += self.grav[:n]
        d = 1.0 - self.drag[:n]
        self.vx[:n] *= d
        self.vy[:n] *= d
        self.x[:n] += self.vx[:n]
        self.y[:n] += self.vy[:n]
        self.life[:n] -= 1
        alive = self.life[:n] > 0
        if not alive.all():
            idx = np.nonzero(alive)[0]
            m = len(idx)
            for arr in (self.x, self.y, self.vx, self.vy, self.life, self.maxlife, self.grav, self.drag,
                        self.size, self.ramp):
                arr[:m] = arr[idx]
            self.n = m

    def draw(self, cv):
        n = self.n
        if n == 0:
            return
        frac = 1.0 - self.life[:n] / self.maxlife[:n]
        xs = np.floor(self.x[:n]).astype(np.int32)
        ys = np.floor(self.y[:n]).astype(np.int32)
        sizes = self.size[:n]
        for rid, ramp in enumerate(self.ramps):
            sel = self.ramp[:n] == rid
            if not sel.any():
                continue
            ci = np.minimum((frac[sel] * len(ramp)).astype(np.int32), len(ramp) - 1)
            cols = ramp[ci]
            sx, sy, ss = xs[sel], ys[sel], sizes[sel]
            small = ss < 0.75
            ok = small & (sx >= 0) & (sx < cv.w) & (sy >= 0) & (sy < cv.h)
            cv.px[sy[ok], sx[ok]] = cols[ok]
            if (~small).any():
                fs = frac[sel]
                for j in np.nonzero(~small)[0]:
                    r = ss[j] * (1.0 - 0.7 * fs[j])  # size shrinks over life
                    cv.circle(sx[j], sy[j], r, tuple(int(v) for v in cols[j]))


# --------------------------------------------------------------------------
# misc drawing helpers
# --------------------------------------------------------------------------

def star_glint(cv, x, y, r, c, core=WHITE):
    """Four-point twinkle star."""
    x, y = int(x), int(y)
    r = int(r)
    if r <= 0:
        cv.pset(x, y, core)
        return
    cv.rect(x - r, y, 2 * r + 1, 1, c)
    cv.rect(x, y - r, 1, 2 * r + 1, c)
    if r >= 3:
        cv.rect(x - 1, y - 1, 3, 3, c)
    cv.pset(x, y, core)


def shake_offset(rng, amp):
    if amp <= 0.25:
        return 0, 0
    return int(round((rng.random() * 2 - 1) * amp)), int(round((rng.random() * 2 - 1) * amp))


def shift_canvas(cv, dx, dy):
    """Screen shake: shift the image, replicating the edge pixels."""
    if dx == 0 and dy == 0:
        return
    p = max(abs(dx), abs(dy))
    padded = np.pad(cv.px, ((p, p), (p, p), (0, 0)), mode="edge")
    cv.px[:] = padded[p - dy:p - dy + cv.h, p - dx:p - dx + cv.w]
