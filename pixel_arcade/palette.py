"""Hand-tuned palette. Everything on screen is drawn from these colors."""

INK = (12, 8, 24)          # outline / near black
NIGHT = (22, 14, 44)
DEEP = (34, 22, 74)
INDIGO = (52, 34, 110)
PURPLE = (86, 42, 150)
VIOLET = (134, 62, 198)
ORCHID = (188, 92, 232)
MAGENTA = (238, 62, 198)
PINK = (255, 112, 192)
ROSE = (255, 170, 216)
CRIMSON = (196, 24, 74)
RED = (240, 50, 72)
SCARLET = (255, 92, 70)
ORANGE = (255, 136, 38)
AMBER = (255, 186, 46)
YELLOW = (255, 234, 70)
LEMON = (255, 248, 158)
CREAM = (255, 250, 224)
WHITE = (255, 255, 255)
LIME = (178, 246, 62)
GREEN = (62, 214, 96)
EMERALD = (22, 150, 102)
FOREST = (14, 88, 74)
TEAL = (14, 170, 172)
CYAN = (70, 236, 255)
ICE = (182, 248, 255)
SKY = (84, 168, 255)
BLUE = (50, 98, 232)
COBALT = (38, 58, 168)
NAVY = (24, 32, 102)
STEEL = (96, 110, 158)
SLATE = (62, 70, 112)
GREY = (146, 156, 190)
SILVER = (206, 214, 234)
BROWN = (120, 64, 50)
RUST = (176, 94, 58)
TAN = (226, 160, 108)
SKIN = (255, 204, 164)
SKIN_SH = (224, 144, 116)
GOLD = (255, 200, 40)
GOLD_SH = (206, 120, 20)

# Color ramps used by particles / explosions (bright -> dark).
FIRE = [WHITE, LEMON, YELLOW, AMBER, ORANGE, SCARLET, RED, CRIMSON, (90, 30, 60), (50, 30, 60)]
PLASMA = [WHITE, ICE, CYAN, SKY, BLUE, COBALT, NAVY]
NEON_PINK = [WHITE, ROSE, PINK, MAGENTA, VIOLET, PURPLE, INDIGO]
TOXIC = [WHITE, LEMON, LIME, GREEN, EMERALD, FOREST]
SMOKE = [SILVER, GREY, STEEL, SLATE, INDIGO, DEEP]
GOLDEN = [WHITE, LEMON, YELLOW, GOLD, AMBER, ORANGE, GOLD_SH]
RAINBOW = [RED, ORANGE, YELLOW, LIME, GREEN, CYAN, SKY, VIOLET, MAGENTA, PINK]


def mix(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def shade(c, f):
    return tuple(max(0, min(255, int(round(v * f)))) for v in c)
