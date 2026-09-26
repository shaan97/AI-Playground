"""Hand-drawn sprites (ASCII art -> Sprite)."""
from .engine import Sprite
from .palette import (AMBER, BLUE, COBALT, CRIMSON, CYAN, GOLD, GOLD_SH, GREY, ICE, INK, LEMON, NAVY, DEEP,
                      ORANGE, RED, RUST, SCARLET, SILVER, SKIN, SKIN_SH, SKY, SLATE, STEEL, WHITE, YELLOW, PINK,
                      MAGENTA, VIOLET, PURPLE, INDIGO, ROSE, BROWN)

# --------------------------------------------------------------------------
# Hero: "Comet Kid"
# --------------------------------------------------------------------------
HERO_KEY = {
    "K": INK, "H": ORANGE, "Y": AMBER, "L": LEMON, "h": RUST, "S": SKIN, "s": SKIN_SH, "E": INK,
    "W": WHITE, "P": PINK, "R": RED, "r": CRIMSON, "B": BLUE, "b": COBALT, "C": SKY, "N": NAVY,
    "n": DEEP, "O": SCARLET, "o": CRIMSON, "w": SILVER, "G": SLATE, "c": CYAN, "i": ICE,
}

HERO_HEAD = [
    "......KK.KKK....",
    "....KKYKKYLYK...",
    "..KKYLYHYYYHHK..",
    ".KYYHHHHHHHHHHK.",
    "KhHHHHHHHHHHHHHK",
    ".KhHHHHHHHHHHHHK",
    "KhhHHHHHSHHSHHK.",
    "KhhHHHSSSSSESSK.",
    ".KhhHsSSSSSESSK.",
    "..KhhsSSSSSSSPK.",
    "...KKKsSSSSSKK..",
]

HERO_TORSO_FWD = [      # arm swung forward
    "....KRRRRRRK....",
    "...KbRRRRRRK....",
    "...KbBBBCBBBKK..",
    "...KbBBBCBBKSSK.",
    "...KbbBBBBBKKK..",
]
HERO_TORSO_BACK = [     # arm swung back
    "....KRRRRRRK....",
    "..KKbRRRRRRK....",
    ".KSKbBBBCBBBK...",
    ".KSKbBBBCBBBK...",
    "..KKbbBBBBBK....",
]
HERO_TORSO_UP = [       # fist raised (jump)
    "....KRRRRRRKKK..",
    "...KbRRRRRRKSSK.",
    "...KbBBBCBBKBK..",
    "...KbBBBCBBBK...",
    "...KbbBBBBBK....",
]

# legs: rows start at the belt. near leg = N/O, far leg = n/o
HERO_LEGS = {
    "stand": [
        "....KNNNNNNK....",
        "....KnnKKNNK....",
        "....KnnK.KNNK...",
        "...KooK..KOOK...",
        "...KwwwK.KwwwK..",
        "....KKK...KKK...",
    ],
    "run1": [            # contact: legs spread
        "....KNNNNNNK....",
        "...KnnKKKNNNK...",
        "..KnnK...KNNK...",
        ".KooK.....KNNK..",
        "KwooK.....KOOOK.",
        ".KKK......KwwwK.",
    ],
    "run2": [            # down: near leg under body, far leg lifting behind
        "....KNNNNNNK....",
        "..KKnnKKNNNK....",
        ".KoonK..KNNK....",
        ".KwoK...KNNK....",
        "..KK...KOOOK....",
        ".......KwwwK....",
    ],
    "run3": [            # passing: far leg swinging through, knee forward
        "....KNNNNNNK....",
        ".....KnnNNNK....",
        ".....KnnKNNK....",
        ".....KoonKNNK...",
        "......KKKOOOK...",
        ".........KwwwK..",
    ],
    "run4": [            # push-off: near leg back, far knee high
        "....KNNNNNNnnK..",
        "...KNNNKKKnnooK.",
        "..KNNK...KKwoK..",
        ".KNNK.....KKK...",
        "KOOOK...........",
        "KwwK............",
    ],
    "jump": [            # tucked
        "....KNNNNNNK....",
        "...KnnKKNNNNK...",
        "...KoonK.KNNK...",
        "...KwooK.KOOK...",
        "....KKK..KwwwK..",
        "..........KKK...",
    ],
    "fall": [            # legs dangling
        "....KNNNNNNK....",
        "....KnnKKNNK....",
        "...KnnK..KNNK...",
        "..KooK....KOOK..",
        "..KwwK....KwwwK.",
        "...KK......KKK..",
    ],
}


def _hero_part(rows):
    return Sprite.from_ascii(rows, HERO_KEY)


HERO = {
    "head": _hero_part(HERO_HEAD),
    "torso_fwd": _hero_part(HERO_TORSO_FWD),
    "torso_back": _hero_part(HERO_TORSO_BACK),
    "torso_up": _hero_part(HERO_TORSO_UP),
    **{"legs_" + k: _hero_part(v) for k, v in HERO_LEGS.items()},
}


# --------------------------------------------------------------------------
# Pickups
# --------------------------------------------------------------------------
COIN_KEY = {"K": INK, "Y": GOLD, "L": LEMON, "g": GOLD_SH, "W": WHITE}
_COIN = [
    ["..KKKK..",
     ".KLYYYK.",
     "KLWYYYgK",
     "KLYYYYgK",
     "KLYYYYgK",
     "KLYYYggK",
     ".KYggg K".replace(" ", "g"),
     "..KKKK.."],
    ["..KKKK..",
     "..KLYYK.",
     ".KLWYgK.",
     ".KLYYgK.",
     ".KLYYgK.",
     ".KLYggK.",
     "..KYgK..",
     "..KKKK.."],
    ["...KK...",
     "...KLK..",
     "...KLK..",
     "...KYK..",
     "...KYK..",
     "...KgK..",
     "...KgK..",
     "...KK..."],
]
COIN = [Sprite.from_ascii(f, COIN_KEY) for f in _COIN]
COIN.append(COIN[1].flipped())

STAR_SHARD = Sprite.from_ascii([
    "....K....",
    "...KLK...",
    "...KYK...",
    "KKKLYYKKK",
    "KLLYWYYgK",
    ".KgYYYgK.",
    "..KYgYK..",
    ".KYgKgYK.",
    ".KgK.KgK.",
    ".KK...KK.",
], COIN_KEY)

# --------------------------------------------------------------------------
# City enemies
# --------------------------------------------------------------------------
BOT_KEY = {"K": INK, "V": VIOLET, "L": (206, 120, 240), "v": PURPLE, "d": INDIGO, "W": WHITE, "R": RED,
           "P": PINK, "Y": YELLOW, "G": SLATE, "g": STEEL, "C": CYAN}
_DRONE_BODY = [
    ".....KKKKKK.....",
    "...KKVVVVVVKK...",
    "..KVLLVVVVVVvK..",
    ".KVLVKKKKKKVVvK.",
    ".KVLKWWPRRRKVvK.",
    ".KVVKWPRRRRKVvK.",
    ".KVVKPRRRRRKvvK.",
    ".KvVVKKKKKKVvvK.",
    "..KvvVVVVVvvdK..",
    "...KKddddddKK...",
    ".....KGKKGK.....",
    ".....KCK.KCK....",
]
_DRONE_PROP = [
    ["KKKKKKK.KKKKKKK.", "......KKKK......", ".......KK......."],
    ["...KKKK.KKKK....", "......KKKK......", ".......KK......."],
]
DRONE = [Sprite.from_ascii(p + _DRONE_BODY, BOT_KEY) for p in _DRONE_PROP]

BUG_KEY = {"K": INK, "P": PINK, "M": MAGENTA, "m": PURPLE, "W": WHITE, "E": INK, "Y": YELLOW, "G": SLATE,
           "g": STEEL, "R": ROSE}
_BUG_TOP = [
    ".......KK.......",
    "......KYYK......",
    ".......KK.......",
    ".......KK.......",
    "....KKKKKKKK....",
    "..KKRPMMMMMMKK..",
    ".KRPMMMMKKKKMmK.",
    ".KPMMMMKWWWEKmK.",
    "KPMMMMMKWWWEKmmK",
    "KMMMMMMMKKKKMmmK",
    "KmMMMMMMMMMMmmmK",
    ".KmmmmmmmmmmmmK.",
]
BUG = [
    Sprite.from_ascii(_BUG_TOP + ["..KKgGKKKKgGKK..", "..KgGK....KgGK..", "..KKK......KKK.."], BUG_KEY),
    Sprite.from_ascii(_BUG_TOP + ["..KKKgGKKgGKKK..", "...KgGK..KgGK...", "...KKK....KKK..."], BUG_KEY),
]

CRATE_KEY = {"K": INK, "O": ORANGE, "Y": AMBER, "L": LEMON, "r": RUST, "b": BROWN, "W": WHITE}
CRATE = Sprite.from_ascii([
    "KKKKKKKKKKKKKK",
    "KLLLLLLLLLLLYK",
    "KLYYYYYYYYYYrK",
    "KLYKKYYYYKKYrK",
    "KLYKWLYYLLKYrK",
    "KLYYLLLLLLYYrK",
    "KLYYYLLLLYYYrK",
    "KLYYLLYYLLYYrK",
    "KLYKLYYYYLKYrK",
    "KLYKKYYYYKKYrK",
    "KLYYYYYYYYYYrK",
    "KYrrrrrrrrrrbK",
    "KKKKKKKKKKKKKK",
], CRATE_KEY)

# --------------------------------------------------------------------------
# Ships
# --------------------------------------------------------------------------
SHIP_KEY = {"K": INK, "W": WHITE, "L": SILVER, "M": GREY, "m": STEEL, "d": SLATE, "C": CYAN, "c": SKY,
            "I": ICE, "R": RED, "r": CRIMSON, "O": ORANGE, "Y": YELLOW}
PLAYER_SHIP = Sprite.from_ascii([
    "....KKK...................",
    "...KRRRK..................",
    "...KRrrRK.................",
    "..KKRRrRRKKKKKKK..........",
    ".KdmmKKKMMLLLLLLKKKK......",
    "KdmMMMLLLLLLWWWWLLKCCKK...",
    "KdMMLLWWWWWWWWWLLKCIICCKK.",
    "KrRRRRRRRRRRRRRRRKCCCCCCLK",
    "KdmMMMMLLLLLLLLLLLKKKKLLLK",
    ".KdmmmmMMMMMMMMMMMMMMMMKK.",
    "..KKKKdmmmmmmmmmmmmKKKK...",
    ".......KdRRRRK............",
    "........KKKKK.............",
], SHIP_KEY)

FIGHTER_KEY = {"K": INK, "M": SCARLET, "P": AMBER, "m": CRIMSON, "d": (96, 16, 52), "Y": CYAN, "L": ICE,
               "W": WHITE, "O": ORANGE}
FIGHTER = Sprite.from_ascii([
    "..........KKKK..",
    "........KKPMMK..",
    "......KKPMMmK...",
    "..KKKKPMMMmKKK..",
    ".KLLYKMMMMMMMMK.",
    "KLWLYYKMMMMMMmmK",
    ".KLYYKmmmmmmmmdK",
    "..KKKKmmmmmdKKK.",
    "......KKmmmdK...",
    "........KKmmdK..",
    "..........KKKK..",
], FIGHTER_KEY)

CAPSULE_KEY = {"K": INK, "R": RED, "r": CRIMSON, "O": SCARLET, "W": WHITE, "L": ROSE, "Y": YELLOW}
CAPSULE = Sprite.from_ascii([
    "..KKKKKK..",
    ".KLOOOOrK.",
    "KLOKKKOOrK",
    "KOOKWOKOrK",
    "KOOKWOKOrK",
    "KOOKKKOOrK",
    "KOOKOOOOrK",
    "KOOKOOOOrK",
    ".KrrrrrrK.",
    "..KKKKKK..",
], CAPSULE_KEY)

HEART = Sprite.from_ascii([
    ".KK.KK.",
    "KRRKLRK",
    "KRRRRRK",
    ".KRRRK.",
    "..KRK..",
    "...K...",
], {"K": INK, "R": RED, "L": ROSE})

MINI_SHIP = Sprite.from_ascii([
    ".KK.....",
    "KRRKKKK.",
    "KLLLLCCK",
    ".KKKKKK.",
], {"K": INK, "R": RED, "L": SILVER, "C": CYAN})
