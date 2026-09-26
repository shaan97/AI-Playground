"""Procedurally generated pixel art: spheres, asteroids, stars, bevelled
mechanical hulls, nebula fields. All output is palette-quantized with ordered
dithering so it sits naturally next to the hand-drawn sprites."""
import math

import cv2
import numpy as np
from PIL import Image, ImageDraw

from .engine import BAYER4, Sprite, bayer
from .palette import INK, WHITE


def _quantize(level, ramp, ox=0, oy=0):
    """level: float array in [0, len(ramp)-1] (0 = brightest) -> rgb via dithering."""
    ramp = np.array(ramp, np.uint8)
    n = len(ramp) - 1
    level = np.clip(level, 0, n)
    i = np.floor(level).astype(int)
    f = level - i
    thr = bayer(level.shape[0], level.shape[1], ox, oy)
    idx = np.clip(np.where(f > thr, i + 1, i), 0, n)
    return ramp[idx]


def add_outline(rgb, mask, color=INK):
    h, w = mask.shape
    m = np.zeros((h + 2, w + 2), bool)
    for dy, dx in ((0, 1), (2, 1), (1, 0), (1, 2), (1, 1)):
        m[dy:dy + h, dx:dx + w] |= mask
    out = np.zeros((h + 2, w + 2, 3), np.uint8)
    out[m] = color
    out[1:1 + h, 1:1 + w][mask] = rgb[mask]
    return Sprite(out, m)


def sphere(r, ramp, light=(-0.55, -0.62, 0.56), outline=INK, spec=True, ambient=0.12, crescent=None):
    """Shaded pixel sphere. ramp is ordered bright -> dark."""
    r = int(r)
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1].astype(np.float32)
    d2 = xx * xx + yy * yy
    mask = d2 <= r * r + r * 0.8
    z = np.sqrt(np.clip(r * r - d2, 0, None)) / max(r, 1)
    L = np.array(light, np.float32)
    L /= np.linalg.norm(L)
    inten = np.clip((xx / r) * L[0] + (yy / r) * L[1] + z * L[2], 0, 1)
    inten = ambient + (1 - ambient) * inten
    level = (1 - inten) * (len(ramp) - 1) * 1.05
    rgb = _quantize(level, ramp)
    if spec and r >= 4:
        sx, sy = int(round(r + L[0] * r * 0.5)), int(round(r + L[1] * r * 0.5))
        rgb[sy, sx] = WHITE
        if r >= 9:
            rgb[sy, sx + 1] = WHITE
            rgb[sy + 1, sx] = WHITE
    rgb[~mask] = 0
    if outline is None:
        return Sprite(rgb, mask)
    return add_outline(rgb, mask, outline)


def asteroid(r, ramp, seed, craters=3):
    rng = np.random.default_rng(seed)
    size = int(r * 2 + 5)
    c = size / 2
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    dx, dy = xx - c + 0.5, yy - c + 0.5
    ang = np.arctan2(dy, dx)
    dist = np.sqrt(dx * dx + dy * dy)
    rad = np.full_like(ang, r)
    for k in range(2, 5):
        rad += r * 0.055 * rng.normal() * np.cos(k * ang + rng.random() * 6.28)
    rad += r * 0.03 * np.cos(7 * ang + rng.random() * 6.28)
    mask = dist <= rad
    hgt = np.sqrt(np.clip(1 - (dist / np.maximum(rad, 1)) ** 2, 0, 1))
    gy, gx = np.gradient(cv2.GaussianBlur(hgt, (0, 0), 1.0))
    nx, ny, nz = -gx * r * 0.9, -gy * r * 0.9, np.ones_like(gx) * 0.7
    nn = np.sqrt(nx * nx + ny * ny + nz * nz)
    L = np.array([-0.6, -0.65, 0.5])
    L /= np.linalg.norm(L)
    inten = np.clip((nx * L[0] + ny * L[1] + nz * L[2]) / nn, 0, 1) * 0.9 + 0.1
    level = (1 - inten) * (len(ramp) - 1) * 1.1
    for _ in range(craters):
        cr = rng.uniform(r * 0.15, r * 0.3)
        a = rng.random() * 6.28
        dd = rng.random() * r * 0.55
        cx, cy = c + math.cos(a) * dd, c + math.sin(a) * dd
        d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        inside = d < cr
        level = np.where(inside, level + 1.2, level)
        rim = (d >= cr) & (d < cr + 1.2) & ((xx - cx) + (yy - cy) > 0)
        level = np.where(rim, level - 0.8, level)
    rgb = _quantize(level, ramp)
    rgb[~mask] = 0
    return add_outline(rgb, mask)


def star_polygon(cx, cy, r_out, r_in, rot, n=5):
    pts = []
    for i in range(2 * n):
        rr = r_out if i % 2 == 0 else r_in
        a = rot + i * math.pi / n - math.pi / 2
        pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
    return pts


def faceted_star(r, rot, light_ramp, dark_ramp, outline=INK, n=5, inner=0.46):
    """A bevelled star (each arm split into a lit and a shaded facet)."""
    size = int(r * 2 + 4)
    c = size / 2 - 0.5
    img = Image.new("RGB", (size, size), (0, 0, 0))
    msk = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(img)
    dm = ImageDraw.Draw(msk)
    pts = star_polygon(c, c, r, r * inner, rot, n)
    dm.polygon(pts, fill=255)
    for i in range(n):
        tip = pts[2 * i]
        left = pts[(2 * i - 1) % (2 * n)]
        right = pts[(2 * i + 1) % (2 * n)]
        # facet brightness from arm direction vs light (upper-left)
        a = rot + i * 2 * math.pi / n - math.pi / 2
        lit = 0.5 + 0.5 * math.cos(a - (-2.3))
        ci = int(round((1 - lit) * (len(light_ramp) - 1)))
        cd = int(round((1 - lit) * (len(dark_ramp) - 1)))
        d.polygon([(c, c), tip, left], fill=tuple(light_ramp[ci]))
        d.polygon([(c, c), tip, right], fill=tuple(dark_ramp[cd]))
    rgb = np.array(img)
    mask = np.array(msk) > 0
    rgb[~mask] = 0
    return add_outline(rgb, mask, outline) if outline is not None else Sprite(rgb, mask)


def bevel_shade(mask, ramp, top_light=True, edge=True, grad=0.9, oy=0):
    """Shade a mask like a bevelled metal plate: lit top/left edges, dark
    bottom/right edges, dithered vertical gradient in between."""
    h, w = mask.shape
    ys = np.nonzero(mask.any(axis=1))[0]
    y0, y1 = (ys.min(), ys.max()) if len(ys) else (0, h - 1)
    t = (np.arange(h, dtype=np.float32) - y0) / max(1, y1 - y0)
    level = np.broadcast_to((t * grad * (len(ramp) - 1))[:, None], (h, w)).copy()
    level += 0.6
    if edge:
        up = np.zeros_like(mask)
        up[1:] = mask[:-1]
        left = np.zeros_like(mask)
        left[:, 1:] = mask[:, :-1]
        down = np.zeros_like(mask)
        down[:-1] = mask[1:]
        right = np.zeros_like(mask)
        right[:, :-1] = mask[:, 1:]
        top_edge = mask & ~up
        left_edge = mask & ~left
        bot_edge = mask & ~down
        right_edge = mask & ~right
        level[top_edge | left_edge] = 0
        down2 = np.zeros_like(mask)
        down2[:-2] = mask[2:]
        level[bot_edge] = len(ramp) - 1
        level[mask & ~down2 & ~bot_edge] = np.maximum(level[mask & ~down2 & ~bot_edge], len(ramp) - 2)
        level[right_edge & ~top_edge] = np.maximum(level[right_edge & ~top_edge], len(ramp) - 2)
    rgb = _quantize(level, ramp, 0, oy)
    rgb[~mask] = 0
    return rgb


def value_noise(h, w, scale, seed, octaves=4, tile_x=True):
    """Smooth fractal noise in [0,1], horizontally tileable."""
    rng = np.random.default_rng(seed)
    out = np.zeros((h, w), np.float32)
    amp, tot = 1.0, 0.0
    s = scale
    for _ in range(octaves):
        base = rng.random((h, w)).astype(np.float32)
        border = cv2.BORDER_WRAP if tile_x else cv2.BORDER_REFLECT
        # wrap horizontally by padding manually (GaussianBlur lacks BORDER_WRAP)
        pad = int(s * 3) + 1
        if tile_x:
            base = np.concatenate([base[:, -pad:], base, base[:, :pad]], axis=1)
        blurred = cv2.GaussianBlur(base, (0, 0), s)
        if tile_x:
            blurred = blurred[:, pad:pad + w]
        blurred = (blurred - blurred.mean()) / (blurred.std() + 1e-6)
        out += blurred * amp
        tot += amp
        amp *= 0.5
        s = max(1.0, s / 2)
    out /= tot
    out = (out - out.min()) / (out.max() - out.min() + 1e-6)
    return out


def nebula_layer(h, w, ramp, seed, scale=18, threshold=0.45, gain=1.8, ox=0):
    """Returns (rgb, mask) of dithered cloud bands, tileable in x."""
    n = value_noise(h, w, scale, seed)
    v = np.clip((n - threshold) * gain / (1 - threshold), 0, 1)
    level = (1 - v) * (len(ramp) - 1)
    rgb = _quantize(level, ramp, ox)
    # only keep pixels where cloud density is above ~0 (dithered edge)
    thr = bayer(h, w)
    mask = v > thr * 0.35
    return rgb, mask


def poly_mask(w, h, polys=(), ellipses=(), rects=(), subtract=()):
    """Rasterize shapes into a bool mask using PIL (no antialiasing)."""
    im = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(im)
    for p in polys:
        d.polygon(p, fill=255)
    for e in ellipses:
        d.ellipse(e, fill=255)
    for r in rects:
        d.rectangle(r, fill=255)
    for kind, shape in subtract:
        getattr(d, kind)(shape, fill=0)
    return np.array(im) > 0
