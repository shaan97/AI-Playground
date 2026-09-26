"""Development helper: contact sheets of selected frames from one scene.

    python -m pixel_arcade.preview title 0,24,48,96 out.png
"""
import sys

import cv2
import numpy as np

from .post import Post
from .timeline import make_scene


def contact_sheet(name, frames, out_path, cols=3, scale=2):
    ctx, scene, start, n = make_scene(name)
    post = Post(scale=scale)
    frames = sorted(set(min(n - 1, f) for f in frames))
    shots = []
    for f in range(max(frames) + 1):
        ctx.frame = start + f
        cv, p = scene.render(f)
        if f in frames:
            img = post.process(cv.px.copy(), bloom=p.get("bloom", 1.0), crt=p.get("crt"))
            img = img.copy()
            cv2.putText(img, f"{name} f{f} (g{start + f})", (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (255, 255, 255), 1, cv2.LINE_AA)
            shots.append(img)
    h, w = shots[0].shape[:2]
    rows = (len(shots) + cols - 1) // cols
    sheet = np.zeros((rows * h, cols * w, 3), np.uint8)
    for i, s in enumerate(shots):
        r, c = divmod(i, cols)
        sheet[r * h:(r + 1) * h, c * w:(c + 1) * w] = s
    cv2.imwrite(out_path, cv2.cvtColor(sheet, cv2.COLOR_RGB2BGR))
    return ctx


if __name__ == "__main__":
    name = sys.argv[1]
    frames = [int(x) for x in sys.argv[2].split(",")]
    contact_sheet(name, frames, sys.argv[3], cols=int(sys.argv[4]) if len(sys.argv) > 4 else 3)
