"""Chiptune synthesis: band-limited pulses, NES-style 4-bit triangle, noise,
envelopes, drums, filters and effects. Everything is plain numpy/scipy."""
import numpy as np
from scipy import signal

SR = 48000
_RNG = np.random.default_rng(1234)

NOTE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def midi(name):
    """'C#5' / 'Bb3' -> midi number."""
    n = NOTE[name[0]]
    i = 1
    while i < len(name) and name[i] in "#b":
        n += 1 if name[i] == "#" else -1
        i += 1
    return n + 12 * (int(name[i:]) + 1)


def hz(m):
    return 440.0 * 2.0 ** ((np.asarray(m, dtype=np.float64) - 69.0) / 12.0)


# ---------------------------------------------------------------- oscillators

def _phase(freq):
    freq = np.asarray(freq, np.float64)
    dt = freq / SR
    return np.cumsum(dt) % 1.0, dt


def _blep(t, dt):
    out = np.zeros_like(t)
    m = t < dt
    x = t[m] / dt[m]
    out[m] = x + x - x * x - 1.0
    m = t > 1.0 - dt
    x = (t[m] - 1.0) / dt[m]
    out[m] = x * x + x + x + 1.0
    return out


def pulse(freq, duty=0.5):
    ph, dt = _phase(freq)
    dt = np.broadcast_to(dt, ph.shape)
    x = np.where(ph < duty, 1.0, -1.0)
    x += _blep(ph, dt) - _blep((ph - duty) % 1.0, dt)
    return x - (2 * duty - 1)


def saw(freq):
    ph, dt = _phase(freq)
    dt = np.broadcast_to(dt, ph.shape)
    return 2 * ph - 1 - _blep(ph, dt)


def triangle(freq, steps=16):
    ph, _ = _phase(freq)
    tri = 1 - 4 * np.abs(ph - 0.5)
    if steps:
        tri = np.round((tri + 1) * 0.5 * (steps - 1)) / (steps - 1) * 2 - 1
    return tri


def sine(freq):
    ph, _ = _phase(freq)
    return np.sin(2 * np.pi * ph)


def noise(n, rate=None, rng=_RNG):
    """White noise, optionally sample-and-hold at `rate` Hz (NES-ish grit)."""
    if rate is None or rate >= SR:
        return rng.uniform(-1, 1, n)
    hold = SR / rate
    vals = rng.uniform(-1, 1, int(n / hold) + 2)
    return vals[(np.arange(n) / hold).astype(int)]


# ---------------------------------------------------------------- envelopes / filters

def t_axis(n):
    return np.arange(n) / SR


def adsr(n, gate, a=0.004, d=0.09, s=0.7, r=0.06):
    """n samples total, gate = note-on length in samples."""
    t = t_axis(n)
    env = np.where(t < a, t / max(a, 1e-6), s + (1 - s) * np.exp(-(t - a) / max(d, 1e-6)))
    gt = gate / SR
    level = s + (1 - s) * np.exp(-(gt - a) / max(d, 1e-6)) if gt > a else gt / max(a, 1e-6)
    rel = t >= gt
    env[rel] = level * np.clip(1 - (t[rel] - gt) / max(r, 1e-6), 0, 1)
    return env


def expdecay(n, tau):
    return np.exp(-t_axis(n) / tau)


def lowpass(x, fc, order=2):
    fc = min(fc, SR * 0.45)
    b, a = signal.butter(order, fc / (SR / 2), "low")
    return signal.lfilter(b, a, x)


def highpass(x, fc, order=2):
    b, a = signal.butter(order, fc / (SR / 2), "high")
    return signal.lfilter(b, a, x)


def bandpass(x, lo, hi, order=2):
    b, a = signal.butter(order, [lo / (SR / 2), min(hi, SR * 0.45) / (SR / 2)], "band")
    return signal.lfilter(b, a, x)


def sweep_lowpass(x, f0, f1, tau):
    """Time-varying one-pole lowpass whose cutoff glides f0 -> f1 (block-wise)."""
    out = np.empty_like(x)
    y = 0.0
    blk = 64
    n = len(x)
    for i in range(0, n, blk):
        t = i / SR
        fc = f1 + (f0 - f1) * np.exp(-t / tau)
        a = np.exp(-2 * np.pi * fc / SR)
        seg = x[i:i + blk]
        zi = np.array([y * a])
        o, _ = signal.lfilter([1 - a], [1, -a], seg, zi=zi)
        out[i:i + blk] = o
        y = o[-1] if len(o) else y
    return out


# ---------------------------------------------------------------- drums (pre-rendered)

def _kick(vel=1.0, tone=1.0):
    n = int(0.38 * SR)
    t = t_axis(n)
    f = 44 + 120 * tone * np.exp(-t / 0.028)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.17)
    click = noise(n) * np.exp(-t / 0.0025) * 0.5
    x = np.tanh((body + click) * 1.6) * 0.9
    return x * vel


def _snare(vel=1.0):
    n = int(0.3 * SR)
    t = t_axis(n)
    tone = triangle(185 * (1 + 0.3 * np.exp(-t / 0.01)), steps=0) * np.exp(-t / 0.045) * 0.55
    nz = highpass(noise(n, 30000), 1400) * np.exp(-t / 0.085) * 0.85
    return (tone + nz) * vel


def _hat(vel=1.0, open_=False):
    n = int((0.28 if open_ else 0.06) * SR)
    t = t_axis(n)
    nz = highpass(noise(n), 7500, 2)
    return nz * np.exp(-t / (0.09 if open_ else 0.014)) * vel * 0.6


def _crash(vel=1.0):
    n = int(1.8 * SR)
    t = t_axis(n)
    nz = highpass(noise(n), 3800) * np.exp(-t / 0.55)
    metal = sum(pulse(np.full(n, f), 0.5) for f in (3120.0, 4310.0, 5410.0, 6830.0)) * 0.05
    metal *= np.exp(-t / 0.35)
    return (nz * 0.7 + highpass(metal, 2500)) * vel


def _tom(vel=1.0, pitch=120.0):
    n = int(0.3 * SR)
    t = t_axis(n)
    f = pitch * (1 + 0.6 * np.exp(-t / 0.04))
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.13)
    x += noise(n) * np.exp(-t / 0.006) * 0.2
    return x * vel


DRUMS = {
    "K": _kick(),
    "k": _kick(0.6, 0.8),
    "S": _snare(),
    "s": _snare(0.45),
    "H": _hat(0.9),
    "h": _hat(0.5),
    "O": _hat(0.8, True),
    "C": _crash(),
    "T": _tom(1.0, 170),
    "M": _tom(1.0, 125),
    "L": _tom(1.0, 90),
}


# ---------------------------------------------------------------- instruments

def inst_lead(m, dur, vel=1.0, duty=0.25, vib=0.22, vib_delay=0.14, slide=None, release=0.08, decay=0.12,
              sustain=0.72, tremolo=0.0):
    gate = int(dur * SR)
    n = gate + int(release * SR)
    t = t_axis(n)
    semis = vib * np.sin(2 * np.pi * 5.6 * t) * np.clip((t - vib_delay) / 0.12, 0, 1)
    if slide is not None:
        semis = semis + (slide - m) * np.exp(-t / 0.025)
    f = hz(m) * 2 ** (semis / 12)
    duty_mod = duty + 0.06 * np.sin(2 * np.pi * 0.9 * t)
    x = 0.62 * pulse(f, 0.0 + duty) + 0.38 * pulse(f * 1.0035, np.clip(duty_mod, 0.05, 0.5))
    env = adsr(n, gate, 0.004, decay, sustain, release)
    if tremolo:
        env *= 1 - tremolo * (0.5 + 0.5 * np.sin(2 * np.pi * 14 * t))
    return x * env * vel


def inst_bass(m, dur, vel=1.0, release=0.03):
    gate = int(dur * SR)
    n = gate + int(release * SR)
    f = np.full(n, hz(m))
    x = triangle(f) * 0.75 + sine(f) * 0.45 + pulse(f * 2, 0.125) * 0.10
    env = adsr(n, gate, 0.003, 0.09, 0.8, release)
    return x * env * vel


def inst_arp(ms, dur, vel=1.0, rate=50.0, duty=0.125, release=0.04, decay=0.15, sustain=0.6):
    gate = int(dur * SR)
    n = gate + int(release * SR)
    t = t_axis(n)
    idx = (t * rate).astype(int) % len(ms)
    f = hz(np.asarray(ms))[idx]
    x = pulse(f, duty)
    env = adsr(n, gate, 0.002, decay, sustain, release)
    return x * env * vel


def inst_pluck(m, dur, vel=1.0, duty=0.125):
    gate = int(dur * SR)
    n = gate + int(0.05 * SR)
    f = np.full(n, hz(m))
    x = pulse(f, duty)
    env = adsr(n, gate, 0.002, 0.07, 0.25, 0.05)
    return x * env * vel


def inst_pad(ms, dur, vel=1.0, attack=0.25, release=0.7, bright=2600):
    gate = int(dur * SR)
    n = gate + int(release * SR)
    x = np.zeros(n)
    for m in ms:
        for det in (-0.006, 0.0, 0.0065):
            x += saw(np.full(n, hz(m) * (1 + det)))
    x = lowpass(x / (3 * len(ms)), bright, 2)
    env = adsr(n, gate, attack, 0.4, 0.85, release)
    return x * env * vel


def inst_bell(m, dur, vel=1.0):
    n = int((dur + 1.2) * SR)
    t = t_axis(n)
    f = hz(m)
    x = (np.sin(2 * np.pi * f * t) + 0.5 * np.sin(2 * np.pi * f * 2.76 * t) * np.exp(-t / 0.3)
         + 0.25 * np.sin(2 * np.pi * f * 5.4 * t) * np.exp(-t / 0.12))
    return x * np.exp(-t / 0.7) * vel


# ---------------------------------------------------------------- effects

def pan_gains(p):
    p = float(np.clip(p, -1, 1))
    a = (p + 1) * np.pi / 4
    return np.cos(a), np.sin(a)


def delay_pingpong(x, time_l, time_r, fb=0.3, mix=0.2):
    """x mono -> (L, R) with a ping-pong echo."""
    n = len(x)
    L = np.zeros(n)
    R = np.zeros(n)
    dl, dr = int(time_l * SR), int(time_r * SR)
    src = x.copy()
    g = mix
    shift = 0
    for k in range(6):
        d = dl if k % 2 == 0 else dr
        shift += d
        if shift >= n:
            break
        tgt = L if k % 2 == 0 else R
        tgt[shift:] += src[:n - shift] * g
        g *= fb
    return L, R


def reverb_ir(seconds=1.6, decay=0.45, seed=5):
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = t_axis(n)
    irs = []
    for ch in range(2):
        nz = rng.normal(0, 1, n) * np.exp(-t / decay)
        nz = sweep_lowpass(nz, 9000, 1800, 0.6)
        nz[:int(0.012 * SR)] *= np.linspace(0, 1, int(0.012 * SR))
        irs.append(nz / np.sqrt(np.sum(nz ** 2)))
    return irs


def reverb(L, R, mix=0.15, seconds=1.6, decay=0.45):
    irl, irr = reverb_ir(seconds, decay)
    mono = (L + R) * 0.5
    wl = signal.fftconvolve(mono, irl)[:len(L)]
    wr = signal.fftconvolve(mono, irr)[:len(R)]
    return L + wl * mix, R + wr * mix


def limiter(L, R, ceiling=0.93, look=0.004, release=0.12):
    peak = np.maximum(np.abs(L), np.abs(R))
    g = np.minimum(1.0, ceiling / np.maximum(peak, 1e-9))
    win = int(look * SR)
    from scipy.ndimage import minimum_filter1d, uniform_filter1d
    gm = minimum_filter1d(g, size=2 * win + 1)
    # release smoothing (one-pole) applied only upward
    a = np.exp(-1.0 / (release * SR))
    gs = signal.lfilter([1 - a], [1, -a], gm, zi=[gm[0] * a])[0]
    gs = np.minimum(gs, gm)
    gs = uniform_filter1d(gs, size=win)
    L2, R2 = L * gs, R * gs
    return np.clip(L2, -ceiling, ceiling), np.clip(R2, -ceiling, ceiling)
