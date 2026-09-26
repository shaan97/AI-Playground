"""Render the score + the sound-effect events collected while rendering video
into a mastered stereo track."""
import numpy as np
from scipy.io import wavfile

from . import sfx as SFX
from .score import compose
from .synth import (DRUMS, SR, bandpass, delay_pingpong, highpass, inst_arp, inst_bass, inst_bell, inst_lead,
                    inst_pad, inst_pluck, limiter, lowpass, noise, pan_gains, reverb, sweep_lowpass, t_axis)

STEP = 60.0 / 150.0 / 4.0          # one 16th note in seconds
FRAME = 1.0 / 60.0

LEVEL = {"lead": 0.21, "harm": 0.10, "bass": 0.34, "arp": 0.075, "pluck": 0.085, "pad": 0.16, "bell": 0.12,
         "fx": 0.10}
PAN = {"lead": -0.12, "harm": 0.35, "bass": 0.0, "arp": -0.3, "pluck": 0.3, "pad": 0.0, "bell": 0.1, "fx": 0.0}
DRUM_LEVEL = {"K": 0.52, "k": 0.4, "S": 0.3, "s": 0.2, "H": 0.075, "h": 0.05, "O": 0.07, "C": 0.16, "T": 0.3,
              "M": 0.3, "L": 0.32}
DRUM_PAN = {"K": 0.0, "k": 0.0, "S": 0.05, "s": 0.05, "H": 0.3, "h": 0.3, "O": 0.3, "C": -0.25, "T": -0.35,
            "M": 0.0, "L": 0.35}
SFX_GAIN = {"laser": 0.45, "hit": 0.5, "enemy_shot": 0.55, "shield": 0.6, "coin": 0.85, "explode_s": 0.62,
            "explode_m": 0.62, "explode_l": 0.6, "explode_xl": 0.75, "roar": 0.6, "mega_blast": 0.6,
            "siren": 0.7, "slam": 0.68, "thud": 0.7, "blip": 0.5, "tally": 0.6, "fw_burst": 0.55,
            "fw_launch": 0.6, "boss_shot": 0.7, "comet_beam": 0.72, "boss_laser": 0.62, "launch": 0.8,
            "stomp": 0.8, "smash": 0.75, "crate": 0.8, "jump": 0.7, "land": 0.6, "letter": 0.7,
            "powerdown": 0.8, "alarm": 0.6}


def _place(buf, start, x):
    if start >= len(buf) or len(x) == 0:
        return
    if start < 0:
        x = x[-start:]
        start = 0
    end = min(len(buf), start + len(x))
    buf[start:end] += x[:end - start]


def _riser(n_samples):
    t = t_axis(n_samples)
    k = t / t[-1]
    x = sweep_lowpass(noise(n_samples), 300, 9000, t[-1] * 0.5)
    x = highpass(x, 250)
    return x * k ** 2


def render_music(n_total):
    sc = compose()
    tr = sc.tracks
    buses = {k: np.zeros(n_total) for k in LEVEL}
    for (step, ln, m, vel, opts) in tr["lead"]:
        dur = ln * STEP * (0.92 if ln > 1 else 0.8)
        _place(buses["lead"], int(step * STEP * SR), inst_lead(m, dur, vel, **opts))
    for (step, ln, m, vel, opts) in tr["harm"]:
        dur = ln * STEP * (0.9 if ln > 1 else 0.75)
        _place(buses["harm"], int(step * STEP * SR), inst_lead(m, dur, vel, duty=0.125, vib=0.12, **opts))
    for (step, ln, m, vel, opts) in tr["bass"]:
        dur = ln * STEP * (0.9 if ln > 1 else 0.7)
        _place(buses["bass"], int(step * STEP * SR), inst_bass(m, dur, vel))
    for (step, ln, ms, vel, opts) in tr["arp"]:
        dur = ln * STEP * 0.9
        _place(buses["arp"], int(step * STEP * SR), inst_arp(ms, dur, vel, rate=opts.get("rate", 50.0)))
    for (step, ln, m, vel, opts) in tr["pluck"]:
        _place(buses["pluck"], int(step * STEP * SR), inst_pluck(m, ln * STEP * 0.8, vel))
    for (step, ln, ms, vel, opts) in tr["pad"]:
        _place(buses["pad"], int(step * STEP * SR), inst_pad(ms, ln * STEP, vel, **opts))
    for (step, ln, m, vel, opts) in tr["bell"]:
        _place(buses["bell"], int(step * STEP * SR), inst_bell(m, ln * STEP, vel))
    for (step, ln, name, vel, opts) in tr["fx"]:
        if name == "riser":
            _place(buses["fx"], int(step * STEP * SR), _riser(int(ln * STEP * SR)) * vel)

    L = np.zeros(n_total)
    R = np.zeros(n_total)
    for name, buf in buses.items():
        gl, gr = pan_gains(PAN[name])
        x = buf * LEVEL[name]
        if name == "lead":
            dl, dr = delay_pingpong(x, 0.30, 0.45, fb=0.35, mix=0.22)
            L += dl
            R += dr
        if name == "pluck":
            dl, dr = delay_pingpong(x, 0.15, 0.30, fb=0.3, mix=0.2)
            L += dl
            R += dr
        if name == "pad":            # widen with a short inter-channel delay
            d = int(0.011 * SR)
            L += x * 0.8
            R[d:] += x[:-d] * 0.8
            continue
        L += x * gl * 1.41
        R += x * gr * 1.41
    # drums
    for (step, kind, vel) in tr["drums"]:
        s0 = int(step * STEP * SR)
        x = DRUMS[kind] * vel * DRUM_LEVEL[kind]
        gl, gr = pan_gains(DRUM_PAN[kind])
        _place(L, s0, x * gl * 1.41)
        _place(R, s0, x * gr * 1.41)
    # reverb + gentle glue saturation
    L, R = reverb(L, R, mix=0.2, seconds=1.8, decay=0.5)
    L = np.tanh(L * 1.1) / 1.1
    R = np.tanh(R * 1.1) / 1.1
    return L, R


def render_sfx(events, n_total):
    L = np.zeros(n_total)
    R = np.zeros(n_total)
    cache = {}
    rng = np.random.default_rng(99)
    for frame, name, params in sorted(events, key=lambda e: e[0]):
        fn = SFX.LIBRARY.get(name)
        if fn is None:
            print(f"  (missing sfx: {name})")
            continue
        p = dict(params)
        # a few variants per effect keep repeated sounds from feeling mechanical
        if name.startswith("explode") or name == "fw_burst":
            p["seed"] = int(rng.integers(0, 6))
        key = (name, tuple(sorted((k, v) for k, v in p.items() if k != "pan")))
        if key not in cache or name == "siren":
            cache[key] = fn(p)
        x = cache[key] * SFX_GAIN.get(name, 0.85)
        gl, gr = pan_gains(np.clip(p.get("pan", 0.0), -1, 1) * 0.55)
        s0 = int(round(frame * FRAME * SR))
        _place(L, s0, x * gl * 1.41)
        _place(R, s0, x * gr * 1.41)
    L, R = reverb(L, R, mix=0.1, seconds=1.2, decay=0.35)
    return L, R


def master(events, n_frames, out_wav):
    n_total = int(round(n_frames * FRAME * SR)) + SR // 2
    mL, mR = render_music(n_total)
    sL, sR = render_sfx(events, n_total)
    L = mL * 0.82 + sL * 0.78
    R = mR * 0.82 + sR * 0.78
    # remove DC, tame sub rumble
    L = highpass(L, 28)
    R = highpass(R, 28)
    # normalize to a consistent loudness before the limiter
    rms = np.sqrt(np.mean(np.concatenate([L, R]) ** 2))
    g = 10 ** (-15.5 / 20) / max(rms, 1e-9)
    L, R = limiter(L * g, R * g, ceiling=0.76)    # ~-2.4 dBFS: headroom for AAC overshoot
    n_out = int(round(n_frames * FRAME * SR))
    L, R = L[:n_out], R[:n_out]
    fade = int(0.05 * SR)
    L[-fade:] *= np.linspace(1, 0, fade)
    R[-fade:] *= np.linspace(1, 0, fade)
    data = np.stack([L, R], axis=1)
    wavfile.write(out_wav, SR, (data * 32767).astype(np.int16))
    return data
