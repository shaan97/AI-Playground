"""Render COMET KID to an MP4 (1920x1080, 60 fps, H.264 + AAC).

    python -m pixel_arcade.render                       # full quality -> output/comet_kid.mp4
    python -m pixel_arcade.render --draft               # 960x540, fast encode
    python -m pixel_arcade.render --bars 34:48 --draft  # just the boss fight
    python -m pixel_arcade.render --stills 600,2400     # PNG frames for inspection
"""
import argparse
import os
import time

import cv2

from .audio.mix import master
from .engine import FPS, FRAMES_PER_BAR
from .post import Post, VideoWriter, mux
from .scene import Context
from .timeline import schedule, scene_class

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "output", "comet_kid.mp4"))
    ap.add_argument("--draft", action="store_true", help="960x540 and a fast x264 preset")
    ap.add_argument("--bars", default=None, help="render only bars A:B (simulation still runs from 0)")
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--preset", default="slow")
    ap.add_argument("--stills", default=None, help="comma separated global frames to save as PNG")
    ap.add_argument("--no-video", action="store_true", help="simulate only; write audio + event log")
    args = ap.parse_args()

    post = Post(scale=5)          # always composite at 1080p; drafts are downscaled afterwards
    out_w, out_h = (960, 540) if args.draft else (1920, 1080)
    preset = "veryfast" if args.draft else args.preset
    crf = 20 if args.draft else args.crf

    sched = schedule()
    total = sched[-1][1] + sched[-1][2]
    f0, f1 = 0, total
    if args.bars:
        a, b = args.bars.split(":")
        f0, f1 = int(a) * FRAMES_PER_BAR, min(total, int(b) * FRAMES_PER_BAR)
    stills = {int(x) for x in args.stills.split(",")} if args.stills else set()

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    base = os.path.splitext(args.out)[0]
    tmp_video = base + ".video.mp4"
    tmp_wav = base + ".wav"
    writer = None
    if not args.no_video and not stills:
        writer = VideoWriter(tmp_video, out_w, out_h, FPS, crf=crf, preset=preset)

    ctx = Context()
    t0 = time.time()
    for name, start, n in sched:
        if start >= f1 and not args.no_video:
            break
        scene = scene_class(name)(ctx, n)
        for f in range(n):
            g = start + f
            ctx.frame = g
            cv, p = scene.render(f)
            if g in stills:
                img = post.process(cv.px, p.get("bloom", 1.0), p.get("crt"))
                cv2.imwrite(f"{base}_f{g:05d}.png", cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
            if writer is not None and f0 <= g < f1:
                img = post.process(cv.px, p.get("bloom", 1.0), p.get("crt"))
                if args.draft:
                    img = cv2.resize(img, (out_w, out_h), interpolation=cv2.INTER_AREA)
                writer.write(img)
            if g % 600 == 0:
                el = time.time() - t0
                print(f"  frame {g:5d}/{total}  [{name}]  {el:6.1f}s  ({(g + 1) / max(el, 1e-6):.1f} fps)",
                      flush=True)
    if writer is not None:
        writer.close()
    print(f"video pass done in {time.time() - t0:.1f}s; final score {ctx.score}; events {len(ctx.events)}")
    if stills:
        return

    t1 = time.time()
    master(ctx.events, total, tmp_wav)
    print(f"audio rendered in {time.time() - t1:.1f}s")
    if args.no_video:
        return
    if (f0, f1) != (0, total):
        from scipy.io import wavfile
        sr, full = wavfile.read(tmp_wav)
        a, b = int(f0 / FPS * sr), int(f1 / FPS * sr)
        wavfile.write(tmp_wav, sr, full[a:b])
    mux(tmp_video, tmp_wav, args.out)
    os.remove(tmp_video)
    print(f"wrote {args.out}  ({os.path.getsize(args.out) / 1e6:.1f} MB) in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
