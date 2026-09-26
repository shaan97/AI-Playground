"""Sound effects, synthesized from scratch. Each returns a mono float array."""
import numpy as np

from .synth import (SR, bandpass, expdecay, highpass, hz, inst_bell, lowpass, midi, noise, pulse, saw, sine,
                    sweep_lowpass, t_axis, triangle)


def _n(sec):
    return int(sec * SR)


def _sweep(f0, f1, sec, curve="exp"):
    n = _n(sec)
    k = np.linspace(0, 1, n)
    if curve == "exp":
        return f0 * (f1 / f0) ** k
    return f0 + (f1 - f0) * k


def _seq(notes, step, duty=0.5, tail=0.0, vel=1.0):
    """Quick square-wave note sequence (list of midi or None)."""
    parts = []
    for m in notes:
        n = _n(step)
        if m is None:
            parts.append(np.zeros(n))
        else:
            parts.append(pulse(np.full(n, hz(m)), duty) * np.linspace(1, 0.6, n))
    x = np.concatenate(parts)
    if tail > 0 and notes and notes[-1] is not None:
        n = _n(tail)
        x = np.concatenate([x, pulse(np.full(n, hz(notes[-1])), duty) * 0.6 * expdecay(n, tail / 3)])
    return x * vel


def _add(a, b, offset=0, gain=1.0):
    """Mix b into a at offset (samples), growing a if needed."""
    end = offset + len(b)
    if end > len(a):
        a = np.pad(a, (0, end - len(a)))
    a[offset:end] += b * gain
    return a


def boom(sec=0.5, f0=110, f1=38, noise_amt=1.0, cut0=4000, cut1=300, rate=None, seed=None):
    n = _n(sec)
    t = t_axis(n)
    rng = np.random.default_rng(seed)
    nz = noise(n, rate, rng=rng)
    nz = sweep_lowpass(nz, cut0, cut1, sec * 0.25) * expdecay(n, sec * 0.3)
    f = f1 + (f0 - f1) * np.exp(-t / (sec * 0.12))
    thump = np.sin(2 * np.pi * np.cumsum(f) / SR) * expdecay(n, sec * 0.28)
    return np.tanh((nz * noise_amt * 1.6 + thump * 1.1) * 1.2)


def crackle(sec, density=60, seed=0):
    rng = np.random.default_rng(seed)
    n = _n(sec)
    x = np.zeros(n)
    k = int(sec * density)
    for pos in rng.integers(0, n - 200, k):
        ln = int(rng.integers(40, 160))
        x[pos:pos + ln] += rng.uniform(-1, 1, ln) * np.exp(-np.arange(ln) / 30) * rng.uniform(0.3, 1)
    return highpass(x, 1500) * np.linspace(1, 0.2, n)


# ---------------------------------------------------------------- the library

def crt_on(p):
    n = _n(0.9)
    t = t_axis(n)
    thump = np.sin(2 * np.pi * np.cumsum(55 + 40 * np.exp(-t / 0.05)) / SR) * expdecay(n, 0.15)
    whine = sine(_sweep(1500, 7800, 0.9)) * 0.08 * np.clip(t / 0.3, 0, 1) * expdecay(n, 0.5)
    static = highpass(noise(n), 2000) * 0.35 * np.exp(-t / 0.12)
    return np.tanh((thump * 0.9 + whine + static) * 1.2) * 0.8


def crt_off(p):
    n = _n(0.8)
    t = t_axis(n)
    whine = sine(_sweep(6000, 180, 0.8)) * 0.18 * expdecay(n, 0.35)
    pop = np.zeros(n)
    k = _n(0.5)
    pop[k:k + _n(0.06)] = noise(_n(0.06)) * np.exp(-np.arange(_n(0.06)) / 300) * 0.6
    return whine + lowpass(pop, 3000)


def coin_insert(p):
    clunk = boom(0.12, 180, 90, 0.4, 3000, 800) * 0.6
    ding = _seq([midi("B5")], 0.07, 0.5) * 0.5
    ding2 = pulse(np.full(_n(0.5), hz(midi("E6"))), 0.5) * expdecay(_n(0.5), 0.14) * 0.5
    return np.concatenate([clunk, ding, ding2])


def whoosh(p, sec=0.35, f0=400, f1=5000):
    n = _n(sec)
    k = np.linspace(0, 1, n)
    x = sweep_lowpass(noise(n), f0, f1, sec * 0.4)
    x = highpass(x, max(80.0, f0 * 0.5))
    env = np.sin(np.pi * k) ** 1.5
    return x * env * 1.3


def comet(p):
    n = _n(0.9)
    t = t_axis(n)
    shimmer = sine(_sweep(3200, 900, 0.9)) * 0.25 * expdecay(n, 0.35)
    sparkle = sum(sine(np.full(n, f)) * (np.sin(2 * np.pi * 23 * t + f) > 0.6) for f in (2637, 3136, 3951)) * 0.06
    return shimmer + whoosh(p, 0.9, 800, 7000) * 0.5 + sparkle * expdecay(n, 0.4)


def thud(p):
    return boom(0.25, 150, 55, 0.5, 2500, 400) * 0.8


def slam(p):
    n = _n(1.0)
    t = t_axis(n)
    hit = boom(1.0, 120, 32, 1.0, 6000, 200)
    clang = sum(pulse(np.full(n, f), 0.5) for f in (523.0, 787.0, 1109.0)) * 0.08 * expdecay(n, 0.25)
    return hit * 0.9 + highpass(clang, 400)


def blip(p):
    n = _n(0.03)
    return pulse(np.full(n, 1500.0), 0.5) * np.linspace(1, 0.3, n) * 0.35


def skid(p):
    n = _n(0.35)
    t = t_axis(n)
    nz = bandpass(noise(n), 1500, 4200)
    flutter = 0.6 + 0.4 * np.sin(2 * np.pi * 38 * t)
    return nz * flutter * expdecay(n, 0.15) * 0.8


def dash(p):
    n = _n(0.2)
    tone = pulse(_sweep(250, 1400, 0.2), 0.25) * np.linspace(0.8, 0.1, n) * 0.5
    return tone + whoosh(p, 0.2, 600, 6000) * 0.5


def start(p):
    seq = _seq([midi(x) for x in ("C6", "E6", "G6", "C7")], 0.035, 0.25)
    bell = inst_bell(midi("C7"), 0.3, 0.35) + inst_bell(midi("G6"), 0.3, 0.25)
    out = np.zeros(len(seq) + len(bell))
    out[:len(seq)] += seq * 0.5
    out[len(seq) - _n(0.01):len(seq) - _n(0.01) + len(bell)] += bell
    return out


def wipe(p):
    return whoosh(p, 0.4, 300, 4000) * 0.7


def jump(p):
    n = _n(0.14)
    return pulse(_sweep(330, 980, 0.14), 0.25) * np.linspace(0.9, 0.2, n) * 0.42


def double_jump(p):
    a = pulse(_sweep(600, 1500, 0.1), 0.25) * np.linspace(0.8, 0.2, _n(0.1)) * 0.4
    return np.concatenate([a, a * 0.6])


def land(p):
    return boom(0.08, 110, 60, 0.3, 1500, 500) * 0.5


def coin(p):
    k = int(p.get("pitch", 0))
    b = midi("B5") + k
    x = np.concatenate([pulse(np.full(_n(0.055), hz(b)), 0.5),
                        pulse(np.full(_n(0.28), hz(b + 5)), 0.5) * expdecay(_n(0.28), 0.09)])
    return x * 0.28


def crate(p):
    crunch = boom(0.3, 200, 60, 1.0, 5000, 800, rate=12000) * 0.7
    pops = _seq([midi(x) for x in ("G5", "E5", "C5")], 0.03, 0.5) * 0.3
    out = crunch.copy()
    out[:len(pops)] += pops
    return out


def powerup(p):
    notes = [midi(x) for x in ("C5", "E5", "G5", "C6", "E6", "G6", "C7")]
    seq = _seq(notes, 0.035, 0.25)
    trill = _seq([midi("C7"), midi("E7")] * 5, 0.03, 0.125) * np.linspace(0.7, 0.0, _n(0.03) * 10)
    return np.concatenate([seq, trill]) * 0.4


def stomp(p):
    c = int(p.get("chain", 0))
    n = _n(0.1)
    tone = pulse(_sweep(900 * 2 ** (c * 3 / 12), 220, 0.1), 0.5) * np.linspace(0.8, 0.1, n) * 0.4
    return tone + np.pad(boom(0.1, 140, 60, 0.4, 2000, 600) * 0.6, (0, 0))[:n]


def smash(p):
    b = boom(0.45, 160, 40, 1.0, 7000, 400, rate=16000) * 0.8
    ding = inst_bell(midi("A6"), 0.1, 0.25)[:len(b)]
    b[:len(ding)] += ding
    return b


def alarm(p):
    parts = []
    for i in range(8):
        n = _n(0.15)
        f = 880.0 if i % 2 == 0 else 660.0
        parts.append(pulse(np.full(n, f), 0.5) * 0.3 * (1 - i / 10))
    return np.concatenate(parts)


def beam(p):
    n = _n(2.2)
    t = t_axis(n)
    f = (350 + 250 * t / 2.2) + 60 * np.sin(2 * np.pi * 7 * t)
    x = sine(f) * 0.3 + pulse(f * 2, 0.125) * 0.06
    shim = highpass(noise(n), 5000) * 0.05 * (0.5 + 0.5 * np.sin(2 * np.pi * 11 * t))
    env = np.clip(t / 0.2, 0, 1) * np.clip((2.2 - t) / 0.4, 0, 1)
    return (x + shim) * env


def powerdown(p):
    n = _n(1.2)
    t = t_axis(n)
    f = 1200 * (80 / 1200) ** (t / 1.2)
    step = (np.floor(t * 18) % 2) * 0.3 + 0.7
    x = pulse(f, 0.5) * step * 0.35 * np.clip((1.2 - t) / 0.3, 0, 1)
    rumble = boom(1.2, 60, 30, 0.6, 400, 120) * 0.5
    return x + rumble


def ufo_zoom(p):
    n = _n(0.8)
    t = t_axis(n)
    f = _sweep(300, 1800, 0.8)
    x = sine(f) * 0.3 + saw(f * 0.5) * 0.06
    return x * np.clip(1 - t / 0.8, 0, 1) + whoosh(p, 0.8, 500, 6000) * 0.4


def ship_arrive(p):
    n = _n(0.9)
    t = t_axis(n)
    hum = lowpass(saw(np.full(n, 55.0) + 10 * np.sin(2 * np.pi * 3 * t)), 600) * 0.25
    return whoosh(p, 0.9, 300, 3000) * 0.6 + hum * np.sin(np.pi * t / 0.9)


def board(p):
    clunk = boom(0.12, 200, 90, 0.3, 2500, 700) * 0.5
    jingle = _seq([midi("G5"), midi("C6")], 0.06, 0.25, tail=0.15) * 0.35
    return np.concatenate([clunk, jingle])


def ignite(p):
    n = _n(1.0)
    t = t_axis(n)
    rum = sweep_lowpass(noise(n), 200, 2500, 0.6) * np.clip(t / 0.4, 0, 1) * 0.8
    return np.tanh(rum * 1.5) * 0.8 + crackle(1.0, 40, 3) * 0.3


def launch(p):
    n = _n(2.0)
    roar = sweep_lowpass(noise(n), 3000, 400, 0.8) * expdecay(n, 0.8)
    thump = boom(0.6, 90, 30, 0.2, 800, 100)
    out = np.tanh(roar * 2.0) * 0.8
    out[:len(thump)] += thump * 0.9
    w = whoosh(p, 1.2, 200, 3000)
    out[:len(w)] += w * 0.5
    return out


def laser(p):
    n = _n(0.06)
    return pulse(_sweep(1700, 650, 0.06), 0.25) * np.linspace(0.7, 0.0, n) * 0.16


def hit(p):
    n = _n(0.03)
    return (highpass(noise(n), 3000) * 0.5 + pulse(np.full(n, 2100.0), 0.5) * 0.25) * np.linspace(1, 0, n) * 0.35


def explode_s(p):
    return boom(0.35, 120, 45, 1.0, 5000, 350, rate=14000, seed=p.get("seed")) * 0.55


def explode_m(p):
    return boom(0.6, 100, 38, 1.0, 5000, 250, rate=11000, seed=p.get("seed")) * 0.7


def explode_l(p):
    a = boom(1.1, 90, 30, 1.0, 6000, 180, rate=9000, seed=p.get("seed")) * 0.8
    a = _add(a, boom(0.6, 110, 40, 1.0, 4000, 300, rate=12000), _n(0.12), 0.45)
    return a * 0.85


def explode_xl(p):
    a = boom(1.8, 80, 25, 1.0, 7000, 120, rate=8000) * 0.9
    return _add(a, crackle(1.2, 70, 9), 0, 0.35)


def enemy_shot(p):
    n = _n(0.07)
    return pulse(_sweep(950, 480, 0.07), 0.5) * np.linspace(0.6, 0, n) * 0.16


def shield(p):
    n = _n(0.08)
    t = t_axis(n)
    return (sine(np.full(n, 2400.0)) + sine(np.full(n, 3300.0))) * expdecay(n, 0.02) * 0.1


def roar(p):
    n = _n(1.5)
    t = t_axis(n)
    f = 70 * (1 + 0.25 * np.sin(2 * np.pi * 9 * t)) * (1 - 0.3 * t / 1.5)
    x = saw(f) * 0.7 + pulse(f * 1.5, 0.3) * 0.3
    x = lowpass(np.tanh(x * 2.5), 1400)
    nz = lowpass(noise(n, 8000), 1200) * 0.5
    env = np.clip(t / 0.08, 0, 1) * np.exp(-np.maximum(0, t - 0.7) / 0.35)
    return (x + nz) * env * 0.9


def hp_fill(p):
    parts = []
    for i in range(24):
        n = _n(0.035)
        parts.append(pulse(np.full(n, 330 * 2 ** (i / 12)), 0.25) * 0.22)
    return np.concatenate(parts)


def boss_shot(p):
    n = _n(0.22)
    x = pulse(_sweep(420, 140, 0.22), 0.5) * 0.25 + lowpass(noise(n), 2000) * 0.2
    return x * expdecay(n, 0.08)


def fireball(p):
    n = _n(0.5)
    return (whoosh(p, 0.5, 200, 1500) * 0.6 + crackle(0.5, 50, 4) * 0.3)


def charge_boss(p):
    n = _n(3.2)
    t = t_axis(n)
    f = 90 * (900 / 90) ** (t / 3.2)
    trem = 0.6 + 0.4 * np.sin(2 * np.pi * (6 + 10 * t / 3.2) * t)
    x = lowpass(saw(f), 2500) * trem * np.clip(t / 0.3, 0, 1)
    return x * 0.32


def boss_laser(p):
    n = _n(1.3)
    t = t_axis(n)
    body = np.tanh(saw(np.full(n, 55.0)) * 2 + saw(np.full(n, 82.5)) * 1.5) * 0.4
    whine = sine(np.full(n, 1760.0) + 30 * np.sin(2 * np.pi * 20 * t)) * 0.08
    nz = lowpass(noise(n), 3000) * 0.4
    trem = 0.75 + 0.25 * np.sin(2 * np.pi * 22 * t)
    env = np.clip(t / 0.02, 0, 1) * np.clip((1.3 - t) / 0.3, 0, 1)
    return (body + whine + nz) * trem * env


def charge(p):
    n = _n(1.6)
    t = t_axis(n)
    f = 300 * (2400 / 300) ** (t / 1.6)
    trem = 0.65 + 0.35 * np.sin(2 * np.pi * (8 + 16 * t / 1.6) * t)
    x = (sine(f) * 0.5 + pulse(f, 0.125) * 0.12) * trem * np.clip(t / 0.2, 0, 1)
    sparkle = highpass(noise(n), 8000) * 0.08 * (np.sin(2 * np.pi * 30 * t) > 0.5)
    return (x + sparkle) * 0.45


def comet_beam(p):
    n = _n(2.4)
    t = t_axis(n)
    blast = boom(0.8, 120, 35, 1.0, 8000, 400) * 0.6
    body = sum(saw(np.full(n, f)) for f in (110.0, 110.7, 165.2)) / 3
    body = lowpass(body, 2200) * 0.35
    shine = sine(np.full(n, 1320.0) + 40 * np.sin(2 * np.pi * 6 * t)) * 0.1
    nz = bandpass(noise(n), 800, 6000) * 0.25
    env = np.clip(t / 0.02, 0, 1) * np.clip((2.4 - t) / 0.6, 0, 1)
    return _add((body + shine + nz) * env, blast, 0, 1.0)


def mega_blast(p):
    a = boom(3.2, 70, 22, 1.0, 9000, 90, rate=7000)
    return _add(a, crackle(2.4, 90, 11), _n(0.2), 0.35)


_siren_count = [0]


def siren(p):
    i = _siren_count[0]
    _siren_count[0] += 1
    n = _n(0.34)
    t = t_axis(n)
    f0, f1 = (620, 830) if i % 2 == 0 else (830, 620)
    f = f0 + (f1 - f0) * np.clip(t / 0.3, 0, 1)
    x = pulse(f, 0.5) * 0.18 + sine(f) * 0.12
    return x * np.clip((0.34 - t) / 0.05, 0, 1)


_scale = [midi(x) for x in ("C5", "D5", "E5", "F5", "G5", "A5", "B5", "C6", "D6", "E6", "F6", "G6", "A6")]


def letter(p):
    i = int(p.get("pitch", 0)) % len(_scale)
    n = _n(0.09)
    return pulse(np.full(n, hz(_scale[i])), 0.25) * expdecay(n, 0.04) * 0.3


def tally(p):
    n = _n(0.025)
    return pulse(np.full(n, 1760.0), 0.5) * 0.12


def tally_done(p):
    return inst_bell(midi("E6"), 0.1, 0.25) + np.pad(inst_bell(midi("A6"), 0.1, 0.2), (0, 0))


def record(p):
    seq = _seq([midi(x) for x in ("G5", "C6", "E6", "G6")], 0.05, 0.25, tail=0.3) * 0.35
    bell = inst_bell(midi("C7"), 0.2, 0.2)
    out = np.zeros(max(len(seq), len(bell) + _n(0.15)))
    out[:len(seq)] += seq
    out[_n(0.15):_n(0.15) + len(bell)] += bell
    return out


def lights_on(p):
    n = _n(1.6)
    t = t_axis(n)
    hum = saw(np.full(n, 60.0) * (1 + t / 1.6)) * 0.08 * np.clip(t / 0.2, 0, 1) * expdecay(n, 0.8)
    chord = sum(inst_bell(midi(x), 0.4, 0.18) for x in ("C6", "E6", "G6"))
    out = np.zeros(max(n, len(chord)))
    out[:n] += lowpass(hum, 900)
    out[:len(chord)] += chord
    return out


def star_release(p):
    notes = [midi(x) for x in ("G6", "E6", "C6", "G5")]
    out = np.zeros(_n(1.4))
    for i, m in enumerate(notes):
        b = inst_bell(m, 0.05, 0.16)
        s = _n(0.08 * i)
        out[s:s + len(b)] += b[:len(out) - s]
    return out


def fw_launch(p):
    n = _n(0.5)
    t = t_axis(n)
    f = 900 + 1600 * t / 0.5
    return (sine(f) * 0.08 + highpass(noise(n), 4000) * 0.04) * np.clip(t / 0.05, 0, 1)


def fw_burst(p):
    b = boom(0.9, 90, 35, 0.9, 3500, 250, rate=10000, seed=p.get("seed")) * 0.55
    return _add(b, crackle(1.1, 110, p.get("seed") or 0), _n(0.25), 0.3)


def the_end(p):
    return sum(inst_bell(midi(x), 0.5, 0.12) for x in ("C6", "G6", "E7"))


LIBRARY = {name: fn for name, fn in globals().items() if callable(fn) and not name.startswith("_")
           and name not in ("boom", "crackle", "midi", "hz", "pulse", "saw", "sine", "triangle", "noise",
                            "lowpass", "highpass", "bandpass", "sweep_lowpass", "expdecay", "t_axis",
                            "inst_bell")}
