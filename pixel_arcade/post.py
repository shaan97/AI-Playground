"""High-resolution finishing: crisp 5x upscale, neon bloom, vignette, CRT
power on/off, and the ffmpeg pipes that turn frames into an MP4."""
import subprocess

import cv2
import imageio_ffmpeg
import numpy as np

from .engine import FPS, H, W, clamp, ease_in_cubic, ease_out_cubic

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


class Post:
    def __init__(self, scale=5):
        self.scale = scale
        self.ow, self.oh = W * scale, H * scale
        # vignette is applied at low resolution: at 5x the per-block steps are invisible
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        nx = (xx + 0.5 - W / 2) / (W / 2)
        ny = (yy + 0.5 - H / 2) / (H / 2)
        d = np.sqrt(nx * nx + ny * ny) / np.sqrt(2)
        vig = 1.0 - 0.22 * np.clip((d - 0.45) / 0.55, 0, 1) ** 2
        self.vig = vig[..., None].astype(np.float32)

    @staticmethod
    def glow_source(f):
        mx = f.max(-1)
        mn = f.min(-1)
        lum = f[..., 0] * 0.299 + f[..., 1] * 0.587 + f[..., 2] * 0.114
        w_lum = np.clip((lum - 150.0) / 105.0, 0, 1)
        # saturated, bright colors (neon) glow as well
        sat = (mx - mn) / (mx + 1.0)
        w_neon = np.clip((mx - 180.0) / 75.0, 0, 1) * np.clip(sat * 1.4, 0, 1)
        w = np.maximum(w_lum, w_neon * 0.8)
        return f * (w * w)[..., None]

    def process(self, low, bloom=1.0, crt=None):
        f = low.astype(np.float32)
        base = cv2.resize(np.clip(f * self.vig, 0, 255).astype(np.uint8), (self.ow, self.oh),
                          interpolation=cv2.INTER_NEAREST)
        if bloom > 0:
            src = self.glow_source(f)
            b = cv2.GaussianBlur(src, (0, 0), 1.5) * 0.45 + cv2.GaussianBlur(src, (0, 0), 5.0) * 0.65
            b = np.clip(b * (0.6 * bloom), 0, 255).astype(np.uint8)
            out = cv2.add(base, cv2.resize(b, (self.ow, self.oh), interpolation=cv2.INTER_LINEAR))
        else:
            out = base
        if crt is not None:
            kind, t = crt
            out = crt_on(out, t) if kind == "on" else crt_off(out, t)
        return out


def _glow_line(out, cx, cy, half_w, thick, strength=1.0):
    oh, ow = out.shape[:2]
    x0, x1 = max(0, int(cx - half_w)), min(ow, int(cx + half_w))
    if x1 <= x0:
        return out
    layers = [(thick * 9, 0.10), (thick * 4, 0.25), (thick * 2, 0.5), (thick, 1.0)]
    f = out.astype(np.float32)
    for th, a in layers:
        y0, y1 = max(0, int(cy - th)), min(oh, int(cy + th) + 1)
        f[y0:y1, x0:x1] = f[y0:y1, x0:x1] * (1 - a * strength) + np.array([225, 245, 255], np.float32) * a * strength
    return np.clip(f, 0, 255).astype(np.uint8)


def crt_on(img, t):
    """Classic tube warm-up: a line appears, then snaps open vertically."""
    oh, ow = img.shape[:2]
    out = np.zeros_like(img)
    if t < 0.3:
        k = ease_out_cubic(t / 0.3)
        return _glow_line(out, ow / 2, oh / 2, ow / 2 * k, 3, 0.4 + 0.6 * k)
    if t < 0.62:
        k = ease_out_cubic((t - 0.3) / 0.32)
        hh = max(4, int(oh * k))
        sq = cv2.resize(img, (ow, hh), interpolation=cv2.INTER_AREA).astype(np.float32)
        whiten = 1.0 - k
        sq = sq * (1 - whiten) + 255.0 * whiten
        y0 = (oh - hh) // 2
        out[y0:y0 + hh] = np.clip(sq, 0, 255).astype(np.uint8)
        return out
    a = 1.0 - clamp((t - 0.62) / 0.38)
    f = img.astype(np.float32)
    f = f + (255.0 - f) * (0.35 * a * a)
    return np.clip(f, 0, 255).astype(np.uint8)


def crt_off(img, t):
    """Tube switch-off: squash to a line, shrink to a dot, fade."""
    oh, ow = img.shape[:2]
    out = np.zeros_like(img)
    if t < 0.4:
        k = ease_in_cubic(t / 0.4)
        hh = max(4, int(oh * (1 - k)))
        sq = cv2.resize(img, (ow, hh), interpolation=cv2.INTER_AREA).astype(np.float32)
        sq = sq + (255.0 - sq) * k
        y0 = (oh - hh) // 2
        out[y0:y0 + hh] = np.clip(sq, 0, 255).astype(np.uint8)
        return out
    if t < 0.72:
        k = ease_in_cubic((t - 0.4) / 0.32)
        return _glow_line(out, ow / 2, oh / 2, max(3, ow / 2 * (1 - k)), 3, 1.0)
    k = clamp((t - 0.72) / 0.28)
    r = int(10 * (1 - k)) + 2
    f = np.zeros((oh, ow, 3), np.float32)
    cv2.circle(f, (ow // 2, oh // 2), r * 4, (120 * (1 - k),) * 3, -1)
    cv2.circle(f, (ow // 2, oh // 2), r, (255 * (1 - k),) * 3, -1)
    f = cv2.GaussianBlur(f, (0, 0), 6)
    return np.clip(f, 0, 255).astype(np.uint8)


class VideoWriter:
    def __init__(self, path, w, h, fps=FPS, crf=17, preset="slow"):
        cmd = [FFMPEG, "-y", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
               "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
               "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-tune", "animation",
               "-x264-params", "keyint=600:min-keyint=30",
               "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
               path]
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    def write(self, frame):
        self.p.stdin.write(np.ascontiguousarray(frame).tobytes())

    def close(self):
        self.p.stdin.close()
        if self.p.wait() != 0:
            raise RuntimeError("ffmpeg video encode failed")


def mux(video_path, audio_path, out_path, audio_bitrate="320k"):
    cmd = [FFMPEG, "-y", "-loglevel", "error", "-i", video_path, "-i", audio_path,
           "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", audio_bitrate,
           "-movflags", "+faststart", "-shortest", out_path]
    subprocess.run(cmd, check=True)
