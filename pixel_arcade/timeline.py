"""Scene order and lengths, in bars of 4/4 at 150 BPM (96 frames per bar)."""
from .engine import FRAMES_PER_BAR
from .scene import Context

# (name, length in bars)
SCENES = [
    ("boot", 2),
    ("title", 6),
    ("city", 12),
    ("space", 32),
    ("ending", 9),
]


def scene_class(name):
    if name == "boot":
        from .scenes.boot import Boot
        return Boot
    if name == "title":
        from .scenes.title import Title
        return Title
    if name == "city":
        from .scenes.city import City
        return City
    if name == "space":
        from .scenes.space import SpaceBattle
        return SpaceBattle
    if name == "ending":
        from .scenes.ending import Ending
        return Ending
    raise KeyError(name)


def schedule():
    out, start = [], 0
    for name, n_bars in SCENES:
        n = n_bars * FRAMES_PER_BAR
        out.append((name, start, n))
        start += n
    return out


def make_scene(name, ctx=None):
    ctx = ctx or Context()
    for nm, start, n in schedule():
        if nm == name:
            return ctx, scene_class(nm)(ctx, n), start, n
    raise KeyError(name)
