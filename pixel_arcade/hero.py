"""Comet Kid: composes head/torso/legs sprites and simulates the scarf."""
import math

from .engine import Sprite
from .palette import CRIMSON, INK, RED, SCARLET
from .sprites import HERO, HERO_KEY, HERO_LEGS

_SWAP = str.maketrans({"N": "n", "n": "N", "O": "o", "o": "O"})


def _swapped(rows):
    return Sprite.from_ascii([r.translate(_SWAP) for r in rows], HERO_KEY)


RUN_CYCLE = []
for _name in ("run1", "run2", "run3", "run4"):
    RUN_CYCLE.append((HERO["legs_" + _name], _name))
for _name in ("run1", "run2", "run3", "run4"):
    RUN_CYCLE.append((_swapped(HERO_LEGS[_name]), _name))

_BOB = {"run1": 0, "run2": 1, "run3": 0, "run4": 0}
_ARM = {"run1": "torso_back", "run2": "torso_back", "run3": "torso_fwd", "run4": "torso_fwd"}

HERO_W, HERO_H = 16, 22


class Hero:
    """Draws the kid with feet at (x, y) = bottom-left of a 16x22 box."""

    def __init__(self, n_scarf=8):
        self.scarf = None
        self.n_scarf = n_scarf
        self.t = 0

    def _update_scarf(self, ax, ay, vx, vy, facing):
        back = -facing
        n = self.n_scarf
        if self.scarf is None:
            self.scarf = [[ax + back * i * 2.0, ay + i * 0.5] for i in range(n)]
        speed = min(abs(vx), 3.0)
        flow = 0.35 + 0.65 * speed / 3.0            # 0 = hanging, 1 = streaming
        pts = [[ax, ay]]
        for i in range(1, n):
            u = i / (n - 1)
            spacing = 1.9 * (0.55 + 0.45 * flow)
            wave = math.sin(self.t * 0.33 - i * 0.95) * (0.4 + 2.2 * u) * (0.45 + 0.55 * flow)
            droop = (1.0 - flow) * i * 1.3 + i * 0.15
            lift = max(-2.0, min(2.0, -vy)) * i * 0.35     # jumping up -> scarf trails down
            tx = ax + back * i * spacing
            ty = ay + wave + droop + lift
            # lag behind the previous frame's shape a little for a soft feel
            ox, oy = self.scarf[i]
            k = 0.5 if i > 1 else 1.0
            pts.append([ox + (tx - ox) * k, oy + (ty - oy) * k])
        self.scarf = pts

    def _draw_scarf(self, cv):
        pts = self.scarf
        n = len(pts)
        for i, (x, y) in enumerate(pts):  # outline pass
            w = 2 if i < n - 2 else 1
            cv.rect(x - 1, y - 1, w + 2, w + 2, INK)
        for i, (x, y) in enumerate(pts):
            w = 2 if i < n - 2 else 1
            cv.rect(x, y, w, w, RED)
            if w == 2:
                cv.pset(x, y + 1, CRIMSON)
                cv.pset(x + 1, y + 1, CRIMSON)
        x, y = pts[-1]
        cv.pset(x, y, SCARLET)

    def draw(self, cv, x, y, pose="run", frame=0, facing=1, vx=2.0, vy=0.0, flash=None, arm=None):
        """pose: stand | run | jump | fall.  frame: animation counter (60fps ticks)."""
        self.t += 1
        top = int(round(y)) - HERO_H
        left = int(round(x))
        flip = facing < 0
        if pose == "run":
            legs, name = RUN_CYCLE[(frame // 3) % len(RUN_CYCLE)]
            bob = _BOB[name]
            torso = HERO[arm or _ARM[name]]
        elif pose in ("jump", "fall"):
            legs = HERO["legs_" + pose]
            bob = 0
            torso = HERO[arm or ("torso_up" if pose == "jump" else "torso_fwd")]
        else:
            legs = HERO["legs_stand"]
            bob = 1 if (frame // 30) % 2 else 0
            torso = HERO[arm or "torso_fwd"]
        # neck anchor for scarf (behind the head)
        ax = left + (4 if not flip else 11)
        ay = top + 11 + bob
        self._update_scarf(ax, ay, vx, vy, facing)
        self._draw_scarf(cv)
        kw = {"flip": flip, "color": flash}
        cv.blit(legs, left, top + 16, **kw)
        cv.blit(torso, left, top + 11 + bob, **kw)
        cv.blit(HERO["head"], left, top + bob, **kw)


def draw_hero_scaled(hero, cv, x, y, scale=2, **kw):
    """Draw the hero at an integer scale (title key art). (x, y) = feet, bottom-left."""
    from .engine import Canvas
    import numpy as np
    key = (1, 2, 3)
    off = Canvas(48, 40)
    off.clear(key)
    hero.draw(off, 16, 36, **kw)
    m = np.any(off.px != np.array(key, np.uint8), axis=-1)
    rgb = np.repeat(np.repeat(off.px, scale, 0), scale, 1)
    m = np.repeat(np.repeat(m, scale, 0), scale, 1)
    cv.mask_fill_rgb(m, rgb, x - 16 * scale, y - 36 * scale)
