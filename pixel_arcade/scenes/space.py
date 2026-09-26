"""STAGE 2 - STARWAY: horizontal shoot-'em-up -> WARNING -> MEGA MAW boss ->
STAGE CLEAR. One continuous scene so the ship, power-ups and score carry over.

Timing is in beats (24 frames); enemy waves and boss attacks are scheduled on
the beat grid so the action locks to the music."""
import math

import numpy as np

from ..backgrounds import Space
from ..boss import MegaMaw
from ..engine import (W, H, Particles, clamp, ease_in_cubic, ease_in_out, ease_out_back, ease_out_cubic,
                      lerp, shake_offset, shift_canvas)
from ..logo import logo_letter
from ..palette import (AMBER, BLUE, CRIMSON, CYAN, DEEP, FIRE, GREY, ICE, INK, LEMON, LIME, MAGENTA, NEON_PINK,
                       ORANGE, PINK, PLASMA, RAINBOW, RED, ROSE, SCARLET, SILVER, SKY, SMOKE, WHITE, YELLOW)
from ..procgen import add_outline, asteroid, bevel_shade, poly_mask, sphere
from ..props import StarCore
from ..scene import Scene, card, draw_hud
from ..sprites import CAPSULE, FIGHTER, PLAYER_SHIP

B = 24
SHMUP_END = 44 * B
WARN = 48 * B
BOSS = 56 * B
BOSS_READY = 60 * B
TURRET1_DIE = 72 * B
TURRET2_DIE = 76 * B
LASER_CHARGE = 76 * B
LASER_FIRE = 80 * B
LASER_END = 83 * B
RAGE = 84 * B
CHARGE = 96 * B
COMET_BEAM = 100 * B
DEATH = 104 * B
FINAL = 108 * B
REVEAL = 110 * B
CLEAR = 112 * B
TALLY1 = 116 * B
TALLY2 = 118 * B
TOTAL = 120 * B
RECORD = 122 * B
EXIT = 124 * B

ROCK = [(240, 206, 170), (214, 160, 116), (176, 112, 76), (128, 74, 58), (84, 44, 50)]


def build_carrier():
    w, h = 50, 30
    rgb = np.zeros((h, w, 3), np.uint8)
    mask = np.zeros((h, w), bool)
    hull = [(226, 196, 255), (180, 140, 230), (136, 96, 200), (100, 64, 164), (70, 42, 124), (46, 26, 86)]
    parts = [
        ([(0, 15), (10, 8), (30, 4), (49, 6), (49, 24), (30, 26), (10, 22)], hull),
        ([(14, 4), (24, 0), (40, 0), (44, 5), (26, 7)], [(250, 230, 255)] + hull[:4]),
        ([(14, 26), (26, 23), (44, 25), (40, 29), (24, 29)], hull[1:]),
    ]
    for poly, ramp in parts:
        m = poly_mask(w, h, polys=[poly])
        rgb[m] = bevel_shade(m, ramp)[m]
        mask |= m
    # cockpit + lights
    eye = poly_mask(w, h, ellipses=[(6, 12, 16, 18)])
    rgb[eye] = (255, 90, 170)
    rgb[13, 8:11] = WHITE
    for x in range(20, 46, 5):
        rgb[15, x:x + 2] = (255, 220, 120)
    rgb[20, 18:46] = (60, 30, 90)
    return add_outline(rgb, mask)


def build_mine(r=6):
    return sphere(r, [ROSE, PINK, MAGENTA, (150, 40, 150), (90, 30, 110), DEEP])


class SpaceBattle(Scene):
    def __init__(self, ctx, n):
        super().__init__(ctx, n)
        rng = self.rng
        self.bg = Space(rng)
        self.parts = Particles(9000)
        self.boss = MegaMaw()
        self.star = StarCore()
        self.carrier_spr = build_carrier()
        self.mine_spr = build_mine()
        self.rocks = {r: [asteroid(r, ROCK, s) for s in range(3)] for r in (5, 7, 12, 15)}
        # player
        self.px, self.py = -40.0, 108.0
        self.pvx, self.pvy = 0.0, 0.0
        self.weapon = 1
        self.options = 0
        self.opt_angle = 0.0
        self.shield_t = -99
        # entities
        self.lasers = []            # [x, y, vx, vy, kind]
        self.bullets = np.zeros((0, 5), np.float32)   # x, y, vx, vy, kind
        self.enemies = []
        self.capsules = []
        self.popups = []
        self.rings = []             # shockwaves: [x, y, f0, rmax, color]
        self.flashes = []           # [x, y, f0, r]
        self.shake = 0.0
        self.combo = 0
        self.last_kill = -999
        self.max_combo = 0
        self.kills = 0
        self.last_hit_sfx = -99
        # boss state
        self.bx, self.by = 420.0, 54.0
        self.turrets = [True, True]
        self.boss_alive = True
        self.boss_flash = 0
        self.spiral = 0.0
        self.wave_done = set()
        self.clear_letters = None
        self.tally = {}
        self.beam_hits = 0

    # ------------------------------------------------------------------ spawning
    def add_enemy(self, kind, f, path, hp, spr, score, box, fire=None, drop=None, size=1):
        self.enemies.append({"kind": kind, "f0": f, "path": path, "hp": hp, "spr": spr, "score": score,
                             "box": box, "fire": fire or [], "drop": drop, "flash": 0, "size": size,
                             "x": -999, "y": -999, "dead": False})

    def sine_wave(self, f, y, n=6, amp=22, spacing=12, speed=2.3, fire_at=None, drop_last=None):
        for i in range(n):
            t0 = f + i * spacing
            ph = i * 0.0

            def path(t, t0=t0, y=y, amp=amp, speed=speed, ph=ph):
                tt = t - t0
                return W + 10 - speed * tt, y + amp * math.sin(tt * 0.055 + ph)
            fire = [t0 + fire_at] if fire_at is not None and i % 2 == 0 else []
            self.add_enemy("fighter", t0, path, 1, FIGHTER, 150, (0, 0, 16, 11), fire,
                           drop_last if i == n - 1 else None)
            if drop_last and i == n - 1:
                self.enemies[-1]["deadline"] = t0 + 110

    def swoop(self, f, from_top=True, n=5, spacing=8, x_turn=250):
        for i in range(n):
            t0 = f + i * spacing
            sgn = 1 if from_top else -1

            def path(t, t0=t0, sgn=sgn, x_turn=x_turn):
                tt = t - t0
                # enter from the right edge, arc across and leave to the left
                a = tt * 0.018
                x = W + 10 - tt * 2.4
                y = H / 2 - sgn * (90 - 70 * math.sin(min(a, math.pi)))
                return x, y
            self.add_enemy("fighter", t0, path, 1, FIGHTER, 150, (0, 0, 16, 11),
                           [t0 + 60] if i == 2 else [])

    def v_wave(self, f, y, n=5):
        for i in range(n):
            k = i - n // 2
            t0 = f + abs(k) * 6

            def path(t, t0=t0, k=k, y=y):
                tt = t - t0
                return W + 10 - tt * 2.1, y + k * 13
            self.add_enemy("fighter", t0, path, 1, FIGHTER, 150, (0, 0, 16, 11))

    def rock(self, f, y, r, speed, vy=0.0, x0=None, seed=0):
        spr = self.rocks[r][seed % 3]
        x0 = W + 20 if x0 is None else x0

        def path(t, t0=f, y=y, speed=speed, vy=vy, x0=x0):
            tt = t - t0
            return x0 - speed * tt, y + vy * tt
        hp = {5: 1, 7: 2, 12: 5, 15: 7}[r]
        self.add_enemy("rock", f, path, hp, spr, 100 if r < 10 else 300, (2, 2, spr.w - 2, spr.h - 2),
                       size=2 if r >= 12 else 1)
        self.enemies[-1]["r"] = r

    def mines(self, f):
        for i, y in enumerate((52, 108, 164)):
            def path(t, t0=f + i * 6, y=y, i=i):
                tt = t - t0
                x = W + 10 - min(tt, 60) * 1.6 - max(0, tt - 150) * 1.5
                return x, y + 6 * math.sin(tt * 0.07 + i)
            fires = [f + i * 6 + 48 + k * B for k in range(4)]
            self.add_enemy("mine", f + i * 6, path, 6, self.mine_spr, 400, (0, 0, 14, 14), fires, size=2)
            self.enemies[-1]["deadline"] = f + 4 * B + 12 * i

    def carrier(self, f):
        def path(t, t0=f):
            tt = t - t0
            x = W + 10 - min(tt, 70) * 1.8
            return x, 94 + 30 * math.sin(tt * 0.03)
        fires = [f + 60 + k * 12 for k in range(0, 14)]
        self.add_enemy("carrier", f, path, 26, self.carrier_spr, 3000, (2, 2, 48, 28), fires, "option", size=3)
        self.enemies[-1]["deadline"] = f + int(3.5 * B)

    def waves(self, f):
        plan = [
            (4, lambda: self.sine_wave(f, 62, fire_at=70)),
            (8, lambda: self.sine_wave(f, 152, amp=-22, fire_at=70)),
            (10, lambda: self.rock(f, 40, 12, 1.1, 0.05, seed=0)),
            (11, lambda: self.rock(f, 118, 15, 0.9, -0.03, seed=1)),
            (12, lambda: self.rock(f, 176, 12, 1.2, -0.08, seed=2)),
            (13, lambda: self.rock(f, 80, 7, 1.6, 0.1, seed=1)),
            (14, lambda: self.rock(f, 150, 7, 1.7, -0.1, seed=2)),
            (16, lambda: self.sine_wave(f, 108, n=5, amp=40, spacing=14, speed=2.0, drop_last="triple")),
            (20, lambda: self.v_wave(f, 60)),
            (21, lambda: self.v_wave(f, 156)),
            (22, lambda: self.v_wave(f, 108, n=7)),
            (24, lambda: self.mines(f)),
            (28, lambda: self.carrier(f)),
            (32, lambda: self.swoop(f, True)),
            (33, lambda: self.swoop(f, False)),
            (34, lambda: self.sine_wave(f, 70, n=6, spacing=9, speed=2.8, fire_at=50)),
            (35, lambda: self.sine_wave(f, 146, n=6, amp=-22, spacing=9, speed=2.8)),
            (36, lambda: self.swoop(f, True, n=6, spacing=6)),
            (37, lambda: self.swoop(f, False, n=6, spacing=6)),
            (38, lambda: [self.rock(f + k * 8, 30 + k * 38, 7, 2.2 + 0.2 * (k % 2), 0.0, seed=k) for k in range(5)]),
            (39, lambda: self.v_wave(f, 108, n=7)),
            (40, lambda: self.sine_wave(f, 50, n=8, amp=18, spacing=7, speed=3.0)),
            (41, lambda: self.sine_wave(f, 166, n=8, amp=-18, spacing=7, speed=3.0)),
            (42, lambda: self.v_wave(f, 90, n=7)),
            (42.5, lambda: self.v_wave(f, 130, n=7)),
        ]
        for beat, fn in plan:
            if int(round(beat * B)) == f and beat not in self.wave_done:
                self.wave_done.add(beat)
                fn()

    # ------------------------------------------------------------------ fx
    def explode(self, x, y, size=1, sfx=True, color_ramp=FIRE):
        rng = self.rng
        n = {1: 26, 2: 60, 3: 120, 4: 220}[size]
        self.parts.burst(rng, x, y, n, 1.2 + size * 0.9, 16 + size * 8, color_ramp, drag=0.06)
        self.parts.burst(rng, x, y, 3 + size * 3, 0.5 + size * 0.3, 30 + size * 10, SMOKE, size=1.5 + size * 0.6,
                         drag=0.05, size_jitter=1.0)
        self.parts.burst(rng, x, y, 4 + 2 * size, 2.5 + size, 18 + size * 6, [WHITE, LEMON, AMBER, ORANGE],
                         drag=0.01)
        self.rings.append([x, y, self.frame, 8 + size * 8, [WHITE, LEMON, AMBER, ORANGE, SCARLET, CRIMSON]])
        self.flashes.append([x, y, self.frame, 3 + size * 3])
        self.shake = max(self.shake, [0, 1.5, 3, 5, 8][size])
        if sfx:
            self.ctx.sfx(["", "explode_s", "explode_m", "explode_l", "explode_xl"][size], pan=clamp(x / W * 2 - 1, -1, 1))

    def popup(self, text, x, y, col=WHITE, life=40):
        self.popups.append([text, x, y, self.frame, col, life])

    def kill(self, e):
        e["dead"] = True
        cx = e["x"] + e["spr"].w / 2
        cy = e["y"] + e["spr"].h / 2
        self.explode(cx, cy, e["size"])
        if self.frame - self.last_kill < 50:
            self.combo += 1
        else:
            self.combo = 1
        self.last_kill = self.frame
        self.max_combo = max(self.max_combo, self.combo)
        self.kills += 1
        pts = e["score"] * (1 + self.combo // 5)
        self.ctx.add_score(pts)
        if e["size"] >= 2 or self.combo % 5 == 0:
            self.popup(str(pts), cx, cy - 8, YELLOW if e["size"] >= 2 else WHITE)
        if e["kind"] == "rock" and e.get("r", 0) >= 12:
            for k in range(3):
                a = k * 2.1 + self.rng.random()
                self.rock(self.frame, cy + math.sin(a) * 4, 5, 1.2 + math.cos(a) * 0.9, math.sin(a) * 0.9,
                          x0=cx + math.cos(a) * 4, seed=k)
        if e["drop"]:
            self.capsules.append({"x": cx, "y": cy, "kind": e["drop"], "f0": self.frame})

    # ------------------------------------------------------------------ player AI
    def threats(self):
        bul = self.bullets[:, :4] if len(self.bullets) else np.zeros((0, 4), np.float32)
        bodies = []
        for e in self.enemies:
            if not e["dead"] and -30 < e["x"] < self.px + 90:
                vx = -2.0 if e["kind"] != "carrier" else 0.0
                bodies.append([e["x"] + e["spr"].w / 2, e["y"] + e["spr"].h / 2, vx, 0.0])
        return bul, np.array(bodies, np.float32).reshape(-1, 4)

    def autopilot(self, f, tx, ty, hazard=None):
        """Choose a velocity by simulating threats a few frames ahead."""
        bul, bod = self.threats()
        K = 18
        t = np.arange(1, K + 1, dtype=np.float32)
        wt = 1.0 / np.sqrt(t)
        best, best_v = -1e9, (0.0, 0.0)
        cx0, cy0 = self.px + 13, self.py + 6
        for dx in (-2.6, 0.0, 2.6):
            for dy in (-3.4, -1.7, 0.0, 1.7, 3.4):
                vx = lerp(self.pvx, dx, 0.35)
                vy = lerp(self.pvy, dy, 0.35)
                xs = np.clip(cx0 + vx * t, 16, W - 60)
                ys = np.clip(cy0 + vy * t, 22, H - 14)
                score = 0.0
                for th, rad in ((bul, 12.0), (bod, 17.0)):
                    if len(th):
                        bx = th[:, 0:1] + th[:, 2:3] * t[None, :]
                        by = th[:, 1:2] + th[:, 3:4] * t[None, :]
                        d = np.sqrt(((bx - xs[None, :]) * 0.7) ** 2 + (by - ys[None, :]) ** 2)
                        dmin = d.min(axis=0)
                        score -= float((np.clip(rad - dmin, 0, None) ** 2 * wt).sum()) * 0.15
                if hazard is not None:
                    y0, y1 = hazard
                    inside = (ys > y0 - 12) & (ys < y1 + 12)
                    score -= float(inside.sum()) * 40
                score -= abs(ty - ys[-1]) * 1.3 + abs(tx - xs[-1]) * 0.45
                # stay out of the corners
                score -= max(0.0, 34 - xs[-1]) * 2 + max(0.0, 30 - ys[-1]) * 2 + max(0.0, ys[-1] - (H - 30)) * 2
                if score > best:
                    best, best_v = score, (dx, dy)
        self.pvx = lerp(self.pvx, best_v[0], 0.35)
        self.pvy = lerp(self.pvy, best_v[1], 0.35)
        self.px = clamp(self.px + self.pvx, 4, W - 80)
        self.py = clamp(self.py + self.pvy, 18, H - 22)

    def pick_target(self, f):
        if self.capsules:
            c = self.capsules[0]
            return c["x"] - 13, c["y"] - 6
        cands = [e for e in self.enemies if not e["dead"] and self.px + 20 < e["x"] < W - 2]
        if not cands:
            return 80 + 20 * math.sin(f * 0.02), 108 + 40 * math.sin(f * 0.013)

        def prio(e):
            p = e["x"] + abs(e["y"] - self.py) * 0.8
            if e["kind"] == "carrier" or e["drop"]:
                p -= 150
            return p
        e = min(cands, key=prio)
        # lead the target by the time the laser needs to reach it
        lead = (e["x"] - self.px) / 7.0
        x2, y2 = e["path"](f + lead)
        return clamp(e["x"] - 140, 40, 140), y2 + e["spr"].h / 2 - 6

    # ------------------------------------------------------------------ shooting
    def fire(self, f):
        if f % 6 != 0:
            return
        x, y = self.px + 24, self.py + 7
        self.lasers.append([x, y, 7.0, 0.0, 0])
        if self.weapon >= 2:
            self.lasers.append([x - 2, y - 2, 6.6, -1.5, 0])
            self.lasers.append([x - 2, y + 2, 6.6, 1.5, 0])
        for i in range(self.options):
            ox, oy = self.option_pos(i)
            self.lasers.append([ox + 3, oy, 7.0, 0.0, 1])
        if f % 12 == 0:
            self.ctx.sfx("laser", pan=clamp(self.px / W * 2 - 1, -1, 1))

    def option_pos(self, i):
        a = self.opt_angle + i * math.pi
        return self.px + 10 + math.cos(a) * 20, self.py + 6 + math.sin(a) * 16

    def enemy_fire(self, x, y, aimed=True, n=1, spread=0.25, speed=2.0, kind=0):
        tx, ty = self.px + 13, self.py + 6
        base = math.atan2(ty - y, tx - x) if aimed else math.pi
        new = []
        for k in range(n):
            a = base + (k - (n - 1) / 2) * spread
            new.append([x, y, math.cos(a) * speed, math.sin(a) * speed, kind])
        self.bullets = np.concatenate([self.bullets, np.array(new, np.float32)])

    def ring_fire(self, x, y, n, speed, offset=0.0, kind=0):
        a = offset + np.arange(n) * (2 * math.pi / n)
        new = np.stack([np.full(n, x), np.full(n, y), np.cos(a) * speed, np.sin(a) * speed, np.full(n, kind)], 1)
        self.bullets = np.concatenate([self.bullets, new.astype(np.float32)])

    # ------------------------------------------------------------------ boss
    def boss_hp(self, f):
        pts = [(BOSS_READY, 1.0), (TURRET1_DIE, 0.82), (TURRET2_DIE, 0.7), (RAGE, 0.55), (CHARGE, 0.2),
               (COMET_BEAM, 0.13), (DEATH, 0.0)]
        if f < BOSS_READY:
            return clamp((f - (BOSS + 2 * B)) / (2 * B))
        for (f0, h0), (f1, h1) in zip(pts[:-1], pts[1:]):
            if f0 <= f < f1:
                return lerp(h0, h1, (f - f0) / (f1 - f0))
        return 0.0

    def boss_pos(self, f):
        if f < BOSS_READY:
            k = ease_out_cubic((f - BOSS) / (BOSS_READY - BOSS))
            x = lerp(420, 200, k)
        elif f < DEATH:
            x = 200 + 8 * math.sin(f * 0.013)
        else:
            k = (f - DEATH) / (FINAL - DEATH)
            x = 200 + 30 * k * k
        y = 50 + 14 * math.sin(f * 0.021)
        if LASER_FIRE <= f < LASER_END:
            k = (f - LASER_FIRE) / (LASER_END - LASER_FIRE)
            y = 50 + 14 * math.sin(LASER_FIRE * 0.021) - 18 * math.sin(k * math.pi)
        if f >= DEATH:
            y += (f - DEATH) * 0.12 + ((f % 4) - 1.5)
        return x, y

    def boss_open(self, f):
        if BOSS + 30 <= f < BOSS + 70:          # roar on entry
            return math.sin((f - BOSS - 30) / 40 * math.pi)
        if 68 * B <= f < 76 * B:                # spit fireballs
            ph = (f - 68 * B) % (2 * B)
            return math.sin(clamp(ph / 20) * math.pi) if ph < 20 else 0.0
        if LASER_CHARGE <= f < LASER_FIRE:
            return ease_out_cubic((f - LASER_CHARGE) / (2 * B))
        if LASER_FIRE <= f < LASER_END:
            return 1.0
        if LASER_END <= f < LASER_END + 12:
            return 1 - (f - LASER_END) / 12
        if f >= DEATH:
            return 0.6 + 0.4 * math.sin(f * 0.3)
        return 0.0

    def update_boss(self, f, cv):
        ctx, rng = self.ctx, self.rng
        bx, by = self.boss_pos(f)
        self.bx, self.by = bx, by
        open_amt = self.boss_open(f)
        ex, ey = bx + 75, by + 44
        mx, my = bx + 22, by + 66 + 9 * open_amt
        tops = self.boss.turret_points(open_amt)
        tpos = [(bx + tops[0][0], by + tops[0][1]), (bx + tops[1][0], by + tops[1][1])]

        if f == BOSS + 30:
            ctx.sfx("roar")
            self.shake = 6
        if f == BOSS + 2 * B:
            ctx.sfx("hp_fill")
        # --- attacks
        if BOSS_READY <= f < 68 * B and (f - BOSS_READY) % B == 0:
            k = (f - BOSS_READY) // B
            self.ring_fire(ex, ey, 14, 1.6, offset=k * 0.22)
            ctx.sfx("boss_shot")
        if 68 * B <= f < TURRET2_DIE:
            if (f - 68 * B) % 12 == 0:
                i = 0 if f < TURRET1_DIE else 1
                if self.turrets[i]:
                    tx_, ty_ = tpos[i]
                    self.enemy_fire(tx_ - 10, ty_, True, 3, 0.22, 2.2)
                    ctx.sfx("enemy_shot")
            if (f - 68 * B) % (2 * B) == 10:
                self.enemy_fire(mx, my, True, 1, 0, 1.4, kind=1)
                ctx.sfx("fireball")
        if LASER_CHARGE <= f < LASER_FIRE:
            if f == LASER_CHARGE:
                ctx.sfx("charge_boss")
            for _ in range(3):
                a = rng.random() * math.tau
                r = 40 + rng.random() * 30
                self.parts.emit(mx + math.cos(a) * r, my + math.sin(a) * r, -math.cos(a) * r / 18,
                                -math.sin(a) * r / 18, 18, NEON_PINK)
        if f == LASER_FIRE:
            ctx.sfx("boss_laser")
        if RAGE <= f < CHARGE:
            if f == RAGE:
                ctx.sfx("roar")
                self.shake = 6
                self.popup("RAGE MODE!", ex, ey - 30, RED, 60)
            if f % 4 == 0:
                self.spiral += 0.23
                for s in (0, math.pi):
                    a = self.spiral + s
                    self.bullets = np.concatenate([self.bullets, np.array(
                        [[ex, ey, math.cos(a) * 1.9, math.sin(a) * 1.9, 0]], np.float32)])
            if (f - RAGE) % (2 * B) == 0:
                self.ring_fire(ex, ey, 20, 1.3, offset=f * 0.01, kind=2)
                ctx.sfx("boss_shot")
        if CHARGE <= f < COMET_BEAM and (f - CHARGE) % B == 0:
            self.ring_fire(ex, ey, 12, 1.2, offset=f * 0.05, kind=2)
            ctx.sfx("boss_shot")
        # --- scripted turret deaths
        for i, fd in enumerate((TURRET1_DIE, TURRET2_DIE)):
            if f == fd and self.turrets[i]:
                self.turrets[i] = False
                self.explode(*tpos[i], 3)
                self.popup("5000", tpos[i][0], tpos[i][1] - 10, YELLOW)
                ctx.add_score(5000)
        # --- death sequence
        if DEATH <= f < FINAL and (f - DEATH) % 6 == 0:
            ox = rng.uniform(10, 160)
            oy = rng.uniform(10, 95)
            # every chain blast is drawn, but only every other one is voiced so they don't pile up
            self.explode(bx + ox, by + oy, 2 if (f - DEATH) % 24 else 3, sfx=(f - DEATH) % 12 == 0)
        if f == FINAL:
            self.boss_alive = False
            self.explode(ex, ey, 4)
            ctx.sfx("mega_blast")
            ctx.add_score(50000)
            self.parts.burst(rng, ex, ey, 300, 6.0, 60, FIRE, drag=0.03)
            self.parts.burst(rng, ex, ey, 120, 4.0, 70, PLASMA, drag=0.03)
        # --- draw boss
        if self.boss_alive:
            laser_charge = clamp((f - LASER_CHARGE) / (4 * B)) if LASER_CHARGE <= f < LASER_FIRE else 0.0
            if LASER_FIRE <= f < LASER_END:
                laser_charge = 1.0
            aim = (self.px + 13 - ex, self.py + 6 - ey)
            n = math.hypot(*aim) or 1
            # one-off full flashes only on big events; otherwise a steady tint (photosensitivity-safe)
            flash = f in (TURRET1_DIE, TURRET1_DIE + 1, TURRET2_DIE, TURRET2_DIE + 1, RAGE, RAGE + 1)
            tint = None
            if RAGE <= f < DEATH:
                tint = ((255, 40, 60), 0.10 + 0.06 * math.sin(f * 0.1))
            if COMET_BEAM <= f < DEATH:
                tint = ((255, 255, 255), 0.35 + 0.1 * math.sin(f * 0.15))
            if f >= DEATH:
                k = (f - DEATH) / (FINAL - DEATH)
                tint = ((255, 90, 40), 0.25 + 0.45 * k)
            angry = RAGE <= f
            self.boss.draw(cv, bx, by, f, open_amt=open_amt, flash=flash, eye_glow=1.0 if angry else 0.0,
                           turrets=tuple(self.turrets), aim=(aim[0] / n, aim[1] / n), charge=laser_charge,
                           neck_phase=0.0, tint=tint, eye_flash=self.boss_flash > 0)
            if RAGE <= f < DEATH and f % 3 == 0:     # damage smoke
                self.parts.emit(bx + rng.uniform(20, 150), by + rng.uniform(10, 60), 0.6, -0.4, 30, SMOKE,
                                size=2.0)
                if f % 9 == 0:
                    self.parts.emit(bx + rng.uniform(20, 150), by + rng.uniform(10, 60), rng.normal(0, 1),
                                    rng.normal(-1, 0.5), 14, [WHITE, LEMON, AMBER])
        self.boss_flash = max(0, self.boss_flash - 1)
        # boss mouth laser
        if LASER_FIRE <= f < LASER_END:
            self.draw_mouth_laser(cv, f, mx, my)
            self.shake = max(self.shake, 2.5)
            return (my - 13, my + 13)
        return None

    def draw_mouth_laser(self, cv, f, mx, my):
        w = 11 + (f % 3)
        for k, (hw, col) in enumerate(((w + 4, (120, 20, 90)), (w, MAGENTA), (w - 4, PINK), (w - 8, ROSE),
                                       (max(1, w - 11), WHITE))):
            cv.rect(0, my - hw, mx, hw * 2, col)
        for i in range(8):
            y = my + self.rng.normal(0, w * 0.6)
            x = self.rng.uniform(0, mx)
            cv.rect(x, y, self.rng.uniform(6, 20), 1, WHITE)
        cv.circle(mx, my, w + 3, PINK)
        cv.circle(mx, my, w - 2, WHITE)

    def boss_hit_test(self, x, y, open_amt):
        """Return 'eye', 'turret0', 'turret1', 'armor' or None for a point."""
        lx, ly = int(x - self.bx + 1), int(y - self.by + 1)
        ex, ey = 75, 44
        if (lx - ex) ** 2 + (ly - ey) ** 2 < 11 ** 2:
            return "eye"
        tops = self.boss.turret_points(open_amt)
        for i, (tx, ty) in enumerate(tops):
            if self.turrets[i] and (lx - tx) ** 2 + (ly - ty) ** 2 < 9 ** 2:
                return f"turret{i}"
        head = self.boss.head
        if 0 <= lx < head.w and 0 <= ly < head.h and head.mask[ly, lx]:
            return "armor"
        jaw = self.boss.jaws[self.boss.jaw_index(open_amt)]
        if 0 <= lx < jaw.w and 0 <= ly < jaw.h and jaw.mask[ly, lx]:
            return "armor"
        if lx > 136 and 26 < ly < 96:
            return "armor"
        return None

    # ------------------------------------------------------------------ main
    def render(self, f):
        self.frame = f
        cv, ctx, rng = self.cv, self.ctx, self.rng
        boss_phase = BOSS <= f < FINAL + 2

        # background speed: warp on entry, slows for the boss
        warp = 1.0 - clamp(f / (1.5 * B)) if f < 2 * B else 0.0
        if WARN <= f < BOSS:
            warp = 0.3 * math.sin((f - WARN) / (BOSS - WARN) * math.pi)
        if EXIT <= f:
            warp = clamp((f - EXIT) / (2 * B)) * 1.5
        speed = 1.0 + warp * 3
        self.bg.draw(cv, f, speed=speed, warp=warp * 2.5)

        # ---------------------------------------------------------- player
        hazard = None
        if f < 2 * B:                                     # fly in
            k = ease_out_cubic(f / (2 * B))
            self.px, self.py = lerp(-60, 70, k), 104 + math.sin(f * 0.05) * 4
        elif f < REVEAL:
            if boss_phase:
                ex, ey = self.bx + 75, self.by + 44
                if f < BOSS_READY:
                    tx, ty = 70, 108
                elif f < TURRET1_DIE:
                    tops = self.boss.turret_points(0)
                    tx, ty = (70, ey - 6) if f < 68 * B else (80, self.by + tops[0][1] - 6)
                elif f < TURRET2_DIE:
                    tops = self.boss.turret_points(self.boss_open(f))
                    tx, ty = 80, self.by + tops[1][1] - 6
                elif f < LASER_END:
                    tx, ty = 70, 30
                elif f < COMET_BEAM:
                    tx, ty = 64, ey - 6
                else:
                    tx, ty = 60, ey - 6
                if LASER_CHARGE + B <= f < LASER_END + 6:
                    open_amt = self.boss_open(f)
                    my = self.by + 66 + 9 * open_amt
                    hazard = (my - 16, my + 16)
            else:
                tx, ty = self.pick_target(f)
            if COMET_BEAM <= f < DEATH + 12:
                # lock onto the eye while the beam fires
                ey = self.by + 44
                self.py = lerp(self.py, ey - 6, 0.2)
                self.px = lerp(self.px, 60, 0.1)
            else:
                self.autopilot(f, tx, ty, hazard)
        else:
            # victory: drift to the left-center, later fly off with the star
            if f < EXIT:
                self.px = lerp(self.px, 56, 0.05)
                self.py = lerp(self.py, 168 + math.sin(f * 0.05) * 3, 0.05)
            else:
                k = (f - EXIT) / (4 * B)
                self.px = lerp(self.px, 56 + 500 * ease_in_cubic(k), 0.2)
                self.py = lerp(self.py, 168 - 40 * k, 0.1)
        self.opt_angle += 0.09

        # ---------------------------------------------------------- spawns
        if f < SHMUP_END:
            self.waves(f)

        # ---------------------------------------------------------- shooting
        firing = 2 * B <= f < REVEAL and not (CHARGE <= f < DEATH)
        if WARN <= f < BOSS_READY:
            firing = False
        if firing:
            self.fire(f)

        # ---------------------------------------------------------- enemies
        for e in self.enemies:
            if e["dead"]:
                continue
            x, y = e["path"](f)
            e["x"], e["y"] = x, y
            if "deadline" in e and f >= e["deadline"] and 0 < x < W:
                self.kill(e)
                continue
            if x < -60 or y < -60 or y > H + 60:
                if f > e["f0"] + 10:
                    e["dead"] = True
                    e["gone"] = True
                continue
            if f in e["fire"] and 0 < x < W - 10:
                cx, cy = x + e["spr"].w / 2, y + e["spr"].h / 2
                if e["kind"] == "mine":
                    self.ring_fire(cx, cy, 10, 1.4, offset=f * 0.1)
                    ctx.sfx("enemy_shot")
                elif e["kind"] == "carrier":
                    self.enemy_fire(x + 4, cy, True, 3 if (f // 12) % 2 else 1, 0.3, 2.3)
                    if f % 24 == 0:
                        ctx.sfx("enemy_shot")
                else:
                    self.enemy_fire(x, cy, True, 1, 0, 2.0)
                    ctx.sfx("enemy_shot")

        # ---------------------------------------------------------- lasers & collisions
        open_amt = self.boss_open(f) if boss_phase else 0.0
        alive_l = []
        live = [e for e in self.enemies if not e["dead"] and e["x"] > -20]
        for L in self.lasers:
            if live:
                ahead = [e for e in live if 0 < e["x"] - L[0] < 120]
                if ahead:
                    e = min(ahead, key=lambda e: abs(e["y"] + e["spr"].h / 2 - L[1]))
                    dy = e["y"] + e["spr"].h / 2 - L[1]
                    if abs(dy) < 40:
                        k = 0.06 if L[4] == 0 else 0.12
                        L[3] = clamp(L[3] + clamp(dy * k, -0.35, 0.35), -2.6, 2.6)
            L[0] += L[2]
            L[1] += L[3]
            if L[0] > W + 10 or L[1] < -5 or L[1] > H + 5:
                continue
            hit = False
            for e in self.enemies:
                if e["dead"] or e["x"] < -40:
                    continue
                x0, y0, x1, y1 = e["box"]
                if e["x"] + x0 <= L[0] + 8 and L[0] <= e["x"] + x1 and e["y"] + y0 <= L[1] + 1 and L[1] <= e["y"] + y1:
                    e["hp"] -= 1
                    e["flash"] = 3
                    hit = True
                    self.parts.burst(rng, L[0] + 8, L[1], 4, 1.5, 8, [WHITE, LEMON, AMBER], drag=0.1)
                    if e["hp"] <= 0:
                        self.kill(e)
                    elif f - self.last_hit_sfx > 5:
                        ctx.sfx("hit", pan=clamp(L[0] / W * 2 - 1, -1, 1))
                        self.last_hit_sfx = f
                    break
            if not hit and boss_phase and self.boss_alive and L[0] > self.bx - 4:
                part = self.boss_hit_test(L[0] + 8, L[1], open_amt)
                if part is not None:
                    hit = True
                    if part == "armor":
                        self.parts.burst(rng, L[0] + 6, L[1], 3, 1.2, 8, [WHITE, SILVER, GREY], drag=0.1)
                    else:
                        self.boss_flash = 2
                        self.parts.burst(rng, L[0] + 8, L[1], 6, 2.0, 12, NEON_PINK if part == "eye" else FIRE,
                                         drag=0.08)
                        if f - self.last_hit_sfx > 4:
                            ctx.sfx("hit", pan=0.3)
                            self.last_hit_sfx = f
                        ctx.add_score(10)
            if not hit:
                alive_l.append(L)
        self.lasers = alive_l

        # ---------------------------------------------------------- enemy bullets
        if len(self.bullets):
            b = self.bullets
            b[:, 0] += b[:, 2]
            b[:, 1] += b[:, 3]
            keep = (b[:, 0] > -8) & (b[:, 0] < W + 8) & (b[:, 1] > -8) & (b[:, 1] < H + 8)
            # shield: bullets touching the ship's core are absorbed
            cx, cy = self.px + 13, self.py + 6
            d2 = (b[:, 0] - cx) ** 2 + ((b[:, 1] - cy) * 1.4) ** 2
            absorbed = keep & (d2 < 9 ** 2)
            if absorbed.any():
                self.shield_t = f
                for x, y in b[absorbed, :2]:
                    self.parts.burst(rng, x, y, 6, 1.4, 10, PLASMA, drag=0.1)
                ctx.sfx("shield")
            keep &= ~absorbed
            if COMET_BEAM <= f < DEATH + 24:   # the comet beam clears the screen
                keep &= ~(np.abs(b[:, 1] - (self.py + 6)) < 30)
            self.bullets = b[keep]

        # ---------------------------------------------------------- capsules
        for c in list(self.capsules):
            c["x"] -= 0.8
            c["y"] += math.sin((f - c["f0"]) * 0.08) * 0.4
            if abs(c["x"] - (self.px + 13)) < 14 and abs(c["y"] - (self.py + 6)) < 12:
                self.capsules.remove(c)
                ctx.sfx("powerup")
                if c["kind"] == "triple":
                    self.weapon = 2
                    self.popup("TRIPLE SHOT!", self.px + 13, self.py - 10, CYAN, 60)
                else:
                    self.options = 2
                    self.popup("OPTIONS!", self.px + 13, self.py - 10, PINK, 60)
                self.parts.burst(rng, self.px + 13, self.py + 6, 50, 2.8, 26, PLASMA, drag=0.06)
                self.rings.append([self.px + 13, self.py + 6, f, 30, [WHITE, ICE, CYAN, SKY, BLUE]])
                ctx.add_score(1000)
            elif c["x"] < -20:
                self.capsules.remove(c)

        # ============================================================ DRAW
        # rings (shockwaves)
        alive = []
        for r in self.rings:
            dt = f - r[2]
            life = 14
            if dt < life:
                k = dt / life
                rad = 2 + r[3] * ease_out_cubic(k)
                col = r[4][min(len(r[4]) - 1, int(k * len(r[4])))]
                cv.ring(r[0], r[1], rad, col, 2 if r[3] > 20 else 1)
                alive.append(r)
        self.rings = alive

        # enemies
        for e in self.enemies:
            if e["dead"] or e["x"] < -50:
                continue
            spr = e["spr"]
            big = spr.w * spr.h > 300
            col = WHITE if e["flash"] > 0 and not big else None
            tint = (WHITE, 0.45) if e["flash"] > 0 and big else None
            e["flash"] = max(0, e["flash"] - 1)
            if e["kind"] == "mine":
                cx, cy = e["x"] + spr.w / 2, e["y"] + spr.h / 2
                for k in range(6):
                    a = f * 0.08 + k * math.pi / 3
                    cv.line(cx + math.cos(a) * 6, cy + math.sin(a) * 6, cx + math.cos(a) * 10,
                            cy + math.sin(a) * 10, SILVER)
            cv.blit(spr, e["x"], e["y"], color=col, tint=tint)
            if e["kind"] == "fighter" and f % 3 == 0:
                self.parts.emit(e["x"] + spr.w, e["y"] + 5, 1.0, 0, 10, [LEMON, AMBER, ORANGE, CRIMSON])
            if e["kind"] == "carrier" and f % 2 == 0:
                self.parts.emit(e["x"] + spr.w, e["y"] + 10 + rng.random() * 10, 1.4, 0, 14, FIRE)

        # boss
        if boss_phase or (FINAL <= f < FINAL + 30):
            self.update_boss(f, cv)

        # capsules
        for c in self.capsules:
            spr = CAPSULE
            cv.blit(spr, c["x"] - 5, c["y"] - 5, color=WHITE if (f // 4) % 4 == 0 else None)
            cv.text("P" if c["kind"] == "triple" else "O", c["x"], c["y"] - 16, YELLOW, align="center")

        # lasers
        for L in self.lasers:
            if L[4] == 0:
                if L[3] == 0:
                    cv.rect(L[0], L[1] - 1, 10, 3, (120, 220, 255))
                    cv.rect(L[0] + 1, L[1], 9, 1, WHITE)
                else:
                    cv.line(L[0], L[1], L[0] + 8, L[1] + L[3] * 1.2, CYAN)
                    cv.line(L[0] + 1, L[1], L[0] + 7, L[1] + L[3] * 1.0, WHITE)
            else:
                cv.rect(L[0], L[1] - 1, 7, 2, PINK)
                cv.rect(L[0] + 1, L[1] - 1, 5, 1, WHITE)

        # enemy bullets
        for x, y, vx, vy, kind in self.bullets:
            if kind == 1:
                r = 5 + (f // 3) % 2
                cv.circle(x, y, r, ORANGE)
                cv.circle(x, y, r - 2, YELLOW)
                cv.circle(x, y, 1, WHITE)
            elif kind == 2:
                cv.circle(x, y, 2, SKY)
                cv.pset(x, y, WHITE)
            else:
                cv.circle(x, y, 2, MAGENTA if (f // 4) % 2 else PINK)
                cv.pset(x, y, WHITE)

        # player ship + options
        if self.px > -40 and self.px < W + 30:
            flame = 5 + (f % 3) * 2 + int(warp * 10)
            for k in range(flame):
                c = WHITE if k < 2 else CYAN if k < flame * 0.5 else SKY
                cv.rect(self.px - k, self.py + 6 + (k % 2), 1, 2 - (k > flame * 0.7), c)
            if f % 2 == 0:
                self.parts.emit(self.px - 2, self.py + 7, -2.0, rng.normal(0, 0.2), 12, PLASMA)
            cv.blit(PLAYER_SHIP, self.px, self.py)
            for i in range(self.options):
                ox, oy = self.option_pos(i)
                cv.circle(ox, oy, 3, MAGENTA)
                cv.circle(ox, oy, 2, PINK)
                cv.pset(ox - 1, oy - 1, WHITE)
                if f % 3 == 0:
                    self.parts.emit(ox, oy, -0.8, 0, 10, NEON_PINK)
            if f - self.shield_t < 8:
                cv.ring(self.px + 13, self.py + 6, 15, ICE if (f % 2) else CYAN)

        # ---------------------------------------------------------- comet beam (player super)
        if CHARGE <= f < COMET_BEAM:
            k = (f - CHARGE) / (COMET_BEAM - CHARGE)
            if f == CHARGE:
                ctx.sfx("charge")
                self.popup("COMET BEAM!!", W // 2, 40, YELLOW, 4 * B)
            nx, ny = self.px + 28, self.py + 7
            for _ in range(4):
                a = rng.random() * math.tau
                r = 30 + rng.random() * 30
                self.parts.emit(nx + math.cos(a) * r, ny + math.sin(a) * r, -math.cos(a) * r / 14,
                                -math.sin(a) * r / 14, 14, [WHITE, ICE, CYAN, YELLOW])
            cv.circle(nx, ny, 2 + k * 7, CYAN)
            cv.circle(nx, ny, 1 + k * 4, WHITE)
        if COMET_BEAM <= f < DEATH + 12:
            if f == COMET_BEAM:
                ctx.sfx("comet_beam")
                self.shake = 8
            nx, ny = self.px + 28, self.py + 7
            ex = self.bx + 75 if self.boss_alive else W
            hw = 9 + 3 * math.sin(f * 0.9)
            if f >= DEATH:
                hw *= 1 - (f - DEATH) / 12
            hue = (f // 8) % len(RAINBOW)
            cv.rect(nx, ny - hw - 3, ex - nx, 2 * hw + 6, RAINBOW[hue])
            cv.rect(nx, ny - hw, ex - nx, 2 * hw, CYAN)
            cv.rect(nx, ny - hw * 0.6, ex - nx, 2 * hw * 0.6, ICE)
            cv.rect(nx, ny - hw * 0.3, ex - nx, max(1, 2 * hw * 0.3), WHITE)
            for i in range(10):
                y = ny + rng.normal(0, hw)
                x = rng.uniform(nx, ex)
                cv.rect(x, y, rng.uniform(8, 24), 1, WHITE)
            cv.circle(nx, ny, hw + 4, CYAN)
            cv.circle(nx, ny, hw, WHITE)
            if self.boss_alive:
                cv.circle(ex, ny, hw + 8, WHITE)
                self.parts.burst(rng, ex, ny, 10, 3.5, 20, [WHITE, ICE, CYAN, PINK, MAGENTA], drag=0.05)
                self.boss_flash = 2
            self.shake = max(self.shake, 4)

        # star core reveal
        if REVEAL - 12 <= f:
            k = clamp((f - (REVEAL - 12)) / 40)
            kk0 = ease_in_out(clamp((f - CLEAR) / (2 * B)))
            sx = lerp(275, 330, kk0)
            sy = lerp(96, 160, kk0) + math.sin(f * 0.05) * 3
            if f >= EXIT:
                kk = clamp((f - EXIT) / (2 * B))
                sx = lerp(sx, self.px + 40, ease_in_out(kk))
                sy = lerp(sy, self.py + 6, ease_in_out(kk))
            if k > 0:
                self.star.draw(cv, sx, sy, f, scale=0.4 + 0.6 * ease_out_back(k), glow=k)

        # particles, flashes
        self.parts.update()
        self.parts.draw(cv)
        alive = []
        for fl in self.flashes:
            dt = f - fl[2]
            if dt < 3:
                cv.circle(fl[0], fl[1], fl[3] * (1 - dt / 3), WHITE)
                alive.append(fl)
        self.flashes = alive

        # popups
        alive = []
        for p in self.popups:
            text, x, y, f0, col, life = p
            dt = f - f0
            if dt < life:
                alive.append(p)
                if dt < life - 12 or (f // 2) % 2:
                    scale = 2 if text.endswith("!!") else 1
                    cv.text(text, x, y - min(dt, 20) * 0.4, col, scale=scale, shadow=INK,
                            outline=INK if scale > 1 else None, align="center")
        self.popups = alive

        # combo meter
        if self.combo >= 3 and f - self.last_kill < 60 and f < WARN:
            k = 1 - (f - self.last_kill) / 60
            cv.text(f"{self.combo}", W - 12, 40, RAINBOW[(f // 3) % len(RAINBOW)], scale=2, align="right",
                    outline=INK)
            cv.text("HIT COMBO", W - 12, 56, WHITE, align="right")
            cv.rect(W - 66, 65, int(54 * k), 2, YELLOW)

        # ---------------------------------------------------------- overlays
        if WARN <= f < BOSS:
            self.draw_warning(cv, f)
        if FINAL <= f < REVEAL + 12:
            dt = f - FINAL
            if dt < 20:
                r = ease_out_cubic(dt / 20) * 460
                cv.circle(self.bx + 75, self.by + 44, r, WHITE)
            else:
                cv.flash(1 - clamp((dt - 30) / 40))

        # shake (world only)
        if self.shake > 0.3:
            dx, dy = shake_offset(rng, self.shake)
            shift_canvas(cv, dx, dy)
        self.shake *= 0.86

        # HUD
        draw_hud(cv, ctx, "ship", f)
        if BOSS + 2 * B <= f < FINAL:
            self.draw_boss_bar(cv, f)
        else:
            self.draw_power(cv, f)
        card(cv, "STAGE 2", "STARWAY", (f - 12) / (2 * 96))
        if f >= CLEAR:
            self.draw_clear(cv, f)
        post = {"bloom": 1.1}
        if f >= self.n - 12:
            cv.flash((f - (self.n - 12)) / 12)
        return cv, post

    # ------------------------------------------------------------------ overlays
    def draw_power(self, cv, f):
        items = [("SHOT", True), ("TRIPLE", self.weapon >= 2), ("OPTION", self.options > 0)]
        x = 8
        for name, on in items:
            w = len(name) * 6 + 5
            cv.rect(x, H - 13, w, 10, (40, 30, 80) if not on else (30, 90, 160))
            cv.rect_outline(x, H - 13, w, 10, INK)
            cv.text(name, x + 3, H - 11, WHITE if on else (110, 100, 150), shadow=None)
            x += w + 3

    def draw_boss_bar(self, cv, f):
        hp = self.boss_hp(f)
        x0, y0, w = 66, H - 12, 308
        cv.text("MEGA MAW", x0 - 4, y0, RED if (f // 8) % 2 == 0 else PINK, align="right")
        cv.rect(x0 - 1, y0 - 1, w + 2, 9, INK)
        cv.rect(x0, y0, w, 7, (60, 20, 40))
        fill = int(w * hp)
        col = LIME if hp > 0.5 else AMBER if hp > 0.25 else RED
        cv.rect(x0, y0, fill, 7, col)
        cv.rect(x0, y0, fill, 2, tuple(min(255, c + 60) for c in col))
        for k in range(1, 8):
            cv.rect(x0 + k * w // 8, y0, 1, 7, INK)

    def draw_warning(self, cv, f):
        t = f - WARN
        # red pulse
        pulse = 0.5 + 0.5 * math.sin(t / B * math.pi)
        cv.tint((170, 0, 30), 0.18 + 0.2 * pulse)
        # hazard stripes, top and bottom, scrolling opposite directions
        for y0, d in ((46, 1), (156, -1)):
            for x in range(-20, W + 20):
                for y in range(y0, y0 + 14):
                    if ((x + d * t * 2 + (y - y0)) // 8) % 2 == 0:
                        cv.pset(x, y, YELLOW)
                    else:
                        cv.pset(x, y, INK)
            cv.rect(0, y0 - 1, W, 1, INK)
            cv.rect(0, y0 + 14, W, 1, INK)
        if (t // 12) % 2 == 0 or t > 6 * B:
            cv.text("WARNING!!", W // 2, 82, RED, scale=4, outline=WHITE, shadow=INK, align="center", ow=1)
        if t > 2 * B:
            msg = "A HUGE ENEMY IS APPROACHING FAST"
            n = min(len(msg), (t - 2 * B) // 2)
            cv.text(msg[:n], W // 2 - len(msg) * 3, 124, WHITE, shadow=INK)
        if t % B == 0:
            self.ctx.sfx("siren")

    def draw_clear(self, cv, f):
        ctx = self.ctx
        word = "STAGE CLEAR!"
        if self.clear_letters is None:
            self.clear_letters = [logo_letter(ch, 3, [LEMON, YELLOW, AMBER, ORANGE, SCARLET, CRIMSON, CRIMSON],
                                              [CRIMSON, (120, 16, 60)], depth=3) if ch != " " else None
                                  for ch in word]
        pitch = 18
        x0 = W // 2 - (len(word) * pitch) // 2
        for i, spr in enumerate(self.clear_letters):
            land = CLEAR + i * 6
            if spr is None or f < land - 10:
                continue
            k = clamp((f - (land - 10)) / 10)
            y = lerp(-30, 44, ease_out_back(k))
            y += math.sin((f + i * 8) * 0.12) * 2 if f > CLEAR + 5 * B else 0
            cv.blit(spr, x0 + i * pitch, y)
            if f == land:
                ctx.sfx("letter", pitch=i)
        # tally
        rows = [(TALLY1, "BOSS BONUS", 50000), (TALLY2, "COMBO BONUS", self.max_combo * 500)]
        y = 98
        for (ft, label, val) in rows:
            if f >= ft:
                k = clamp((f - ft) / 36)
                shown = int(val * k)
                cv.text(label, 104, y, CYAN)
                cv.text(f"{shown:>7d}", 280, y, WHITE, align="right")
                if f < ft + 36 and f % 3 == 0:
                    ctx.sfx("tally")
                if f == ft + 36:
                    ctx.sfx("tally_done")
                    if label == "COMBO BONUS":
                        ctx.add_score(val)
            y += 14
        if f >= TOTAL:
            cv.rect(104, y - 2, 176, 1, WHITE)
            cv.text("SCORE", 104, y + 3, YELLOW)
            cv.text(f"{int(ctx.shown_score):>7d}", 280, y + 3, YELLOW, align="right")
        if f >= RECORD:
            if f == RECORD:
                ctx.sfx("record")
            if (f // 4) % 2 == 0:
                cv.text("NEW RECORD!", W // 2, y + 20, RAINBOW[(f // 2) % len(RAINBOW)], scale=2, outline=INK,
                        align="center")
