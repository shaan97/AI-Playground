"""The soundtrack, written bar by bar on the same 150 BPM grid as the visuals
(16 steps per bar, 1 step = 1/16 note = 6 video frames).

The hero leitmotif (G-C-E-G rising arpeggio) opens the title theme in C major,
shapes the city theme's first bar, returns in D major when Comet Kid charges
the Comet Beam, and closes the video in C major."""
from .synth import midi

CHORDS = {
    "C": "C E G", "G": "G B D", "Am": "A C E", "F": "F A C", "Em": "E G B", "D": "D F# A", "B": "B D# F#",
    "Dm": "D F A", "Bb": "Bb D F", "A": "A C# E", "Bm": "B D F#", "G7": "G B D F", "E": "E G# B",
    "Adim": "A C Eb Gb", "Bdim": "B D F Ab", "Dmaj9": "D F# A C# E",
}
PC = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
      "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}


def chord(name, octave=4):
    names = CHORDS[name].split()
    root = PC[names[0]] + 12 * (octave + 1)
    out = []
    for nm in names:
        m = PC[nm] + 12 * (octave + 1)
        while m < root:
            m += 12
        while out and m <= out[-1]:
            m += 12
        out.append(m)
    return out


def root(name, octave=2):
    n = CHORDS[name].split()[0]
    return PC[n] + 12 * (octave + 1)


class Score:
    def __init__(self):
        self.tracks = {k: [] for k in ("lead", "harm", "bass", "arp", "pluck", "pad", "bell", "drums", "fx")}

    # -------------------------------------------------------------- writers
    def mel(self, track, bar, seq, vel=1.0, shift=0, **opts):
        step = bar * 16
        for tok in seq.split():
            name, ln = tok.split(":")
            ln = float(ln)
            if name not in ("-", "r"):
                self.tracks[track].append((step, ln, midi(name) + shift, vel, opts))
            step += ln
        assert abs(step - bar * 16 - round(step - bar * 16)) < 1e-6
        return step

    def bassline(self, bar, chord_name, pattern, vel=1.0, octave=2):
        """pattern tokens: R (root), O (octave up), F (fifth), T (third), - (rest), with :len."""
        step = bar * 16
        r = root(chord_name, octave)
        tri = chord(chord_name, octave)
        for tok in pattern.split():
            k, ln = tok.split(":")
            ln = float(ln)
            m = {"R": r, "O": r + 12, "F": tri[2] if len(tri) > 2 else r + 7, "T": tri[1], "-": None}[k]
            if m is not None:
                self.tracks["bass"].append((step, ln, m, vel, {}))
            step += ln

    def beat(self, bar, **lanes):
        for kind, pat in lanes.items():
            for i, ch in enumerate(pat):
                if ch == "x":
                    self.tracks["drums"].append((bar * 16 + i, kind, 1.0))
                elif ch == "o":
                    self.tracks["drums"].append((bar * 16 + i, kind, 0.55))
                elif ch == ",":
                    self.tracks["drums"].append((bar * 16 + i, kind, 0.3))

    def roll(self, bar, kind, s0, s1, v0, v1, every=1):
        for s in range(s0, s1, every):
            v = v0 + (v1 - v0) * (s - s0) / max(1, s1 - s0 - 1)
            self.tracks["drums"].append((bar * 16 + s, kind, v))

    def stab(self, bar, step, ln, chord_name, octave=4, vel=1.0, rate=50.0):
        self.tracks["arp"].append((bar * 16 + step, ln, chord(chord_name, octave), vel, {"rate": rate}))

    def pad(self, bar, step, ln, notes, vel=1.0, **opts):
        self.tracks["pad"].append((bar * 16 + step, ln, notes, vel, opts))

    def fx(self, bar, step, name, ln=16, vel=1.0):
        self.tracks["fx"].append((bar * 16 + step, ln, name, vel, {}))


def compose():
    s = Score()
    GROOVE = dict(K="x.......x.x.....", S="....x.......x...", H="o.o.o.o.o.o.o.o.")

    # ================================================================ TITLE (bars 2-7), C major
    b = 2
    s.beat(b, C="x...............", K="x...............")
    s.bassline(b, "C", "R:3 -:1 R:1 -:1 R:1 -:1 R:1 -:1 R:1 -:1 R:1 -:3")
    for st in (0, 4, 6, 8, 10, 12):
        s.stab(b, st, 3 if st == 0 else 1, "C", 4, 0.9 if st else 1.0)
    s.beat(b, T="....x.x.........", M="........x.x.....", L="............x...")
    s.roll(b, "S", 13, 16, 0.5, 1.0)
    s.fx(b, 0, "riser", 16)
    theme_c = ["G4:2 C5:2 E5:2 G5:6 E5:2 G5:2", "B5:6 A5:2 G5:4 D5:4", "C6:6 B5:2 A5:4 E5:4",
               "F5:4 G5:2 A5:2 G5:8"]
    prog = ["C", "G", "Am", "F"]
    for i in range(4):
        bb = 3 + i
        s.mel("lead", bb, theme_c[i])
        s.mel("harm", bb, theme_c[i], vel=0.55, shift=-12)
        s.bassline(bb, prog[i], "R:2 O:2 R:2 O:2 R:2 O:2 R:2 O:2")
        for st in (2, 6, 10, 14):
            s.stab(bb, st, 1.5, prog[i], 4, 0.7)
        s.pad(bb, 0, 16, chord(prog[i], 3), 0.5)
        s.beat(bb, **GROOVE)
    s.beat(3, C="x...............")
    s.beat(6, S="....x.......x.xx")
    # bar 7: START pressed -> run up + fill, walk the bass up to A
    s.mel("lead", 7, "C5:1 E5:1 G5:1 C6:1 E6:1 G6:1 C7:4 -:6")
    s.bassline(7, "G", "R:6 R:2", 1.0)
    s.tracks["bass"] += [(7 * 16 + 8, 2, midi("E2"), 1.0, {}), (7 * 16 + 10, 2, midi("F2"), 1.0, {}),
                         (7 * 16 + 12, 2, midi("F#2"), 1.0, {}), (7 * 16 + 14, 2, midi("G#2"), 1.0, {})]
    s.beat(7, C="x...............", K="x.......x.......", S="........x.x.x.xx", T="............x...",
           M=".............x..", L="..............x.")
    s.stab(7, 0, 6, "C", 5, 0.8)

    # ================================================================ CITY (bars 8-19), A minor
    city = ["A4:2 C5:2 E5:2 A5:3 G5:1 E5:2 D5:2 C5:2", "F5:3 E5:1 F5:2 A5:4 G5:2 F5:2 E5:2",
            "E5:2 G5:2 C6:4 B5:2 G5:2 E5:4", "D5:3 E5:1 D5:2 B4:2 G4:4 -:4",
            "A4:2 C5:2 E5:2 A5:3 G5:1 E5:2 D5:2 C5:2", "F5:3 E5:1 F5:2 A5:4 C6:2 A5:2 F5:2",
            "G5:4 E5:2 G5:2 C6:4 D6:4", "B5:6 A5:2 G5:2 A5:2 B5:4"]
    cprog = ["Am", "F", "C", "G"] * 2
    for i in range(8):
        bb = 8 + i
        s.mel("lead", bb, city[i])
        if i >= 4:
            s.mel("harm", bb, city[i], vel=0.45, shift=-12)
        s.bassline(bb, cprog[i], "R:3 R:1 O:2 R:2 F:2 R:2 O:2 R:2")
        for st in (2, 6, 10, 14):
            s.stab(bb, st, 1.5, cprog[i], 4, 0.75)
        s.beat(bb, K="x.....x...x.....", S="....x.......x...", H="o.x.o.x.o.x.o.x.")
    s.beat(8, C="x...............")
    s.beat(12, C="x...............")
    s.beat(11, O="..............x.")
    s.beat(15, S="............xxxx")
    # bar 16: the stop + star twinkle
    s.beat(16, C="x...............", K="x...............", H="........o...o...")
    s.bassline(16, "Am", "R:4 -:4 R:8", 0.7, octave=1)
    s.stab(16, 0, 4, "Am", 4, 1.0)
    for i, nm in enumerate(("E6", "A6", "B6", "E7", "B6")):
        s.tracks["bell"].append((16 * 16 + 6 + 2 * i, 2, midi(nm), 0.8, {}))
    # bars 17-18: the alarm and the theft
    s.beat(17, C="x...............", K="x...x...x...x...")
    s.tracks["arp"].append((17 * 16, 4, [midi("A3"), midi("Eb4"), midi("G4"), midi("C5")], 1.0, {"rate": 60}))
    s.tracks["arp"].append((17 * 16 + 4, 12, chord("Adim", 4), 0.45, {"rate": 30}))
    s.tracks["arp"].append((18 * 16, 16, chord("Bdim", 4), 0.5, {"rate": 30}))
    s.mel("bass", 17, "A1:2 A1:2 A1:2 A1:2 Bb1:2 Bb1:2 Bb1:2 Bb1:2")
    s.mel("bass", 18, "B1:2 B1:2 B1:2 B1:2 C2:2 C2:2 C#2:2 D2:2")
    s.mel("lead", 17, "E6:16", vel=0.55, tremolo=0.6)
    s.mel("lead", 18, "F6:8 E6:8", vel=0.6, tremolo=0.6)
    s.roll(17, "L", 0, 16, 0.3, 0.8, every=2)
    s.roll(18, "M", 0, 16, 0.4, 1.0)
    s.beat(18, K="x...x...x...x...")
    # bar 19: launch build-up (E minor)
    rise = ["E4", "G4", "B4", "E5", "G5", "B5", "E6", "G6", "B6", "E7", "G6", "B6", "E7", "G7", "B6", "E7"]
    for i, nm in enumerate(rise):
        s.tracks["pluck"].append((19 * 16 + i, 1, midi(nm), 0.4 + 0.6 * i / 15, {}))
    for i in range(16):
        s.tracks["bass"].append((19 * 16 + i, 1, midi("E2"), 0.5 + 0.5 * i / 15, {}))
    s.roll(19, "S", 0, 16, 0.25, 1.0)
    s.beat(19, K="x...x...x...x.xx")
    s.mel("lead", 19, "B4:8 D5:4 D#5:4", vel=0.8)
    s.fx(19, 0, "riser", 16)

    # ================================================================ SPACE (bars 20-31), E minor
    sprog = ["Em", "C", "D", "B", "Em", "C", "D", "Em", "Am", "B", "Em"]
    space = ["E5:6 F#5:2 G5:4 B5:4", "C6:8 B5:2 A5:2 G5:4", "A5:6 G5:2 F#5:4 D5:4", "D#5:8 F#5:4 B5:4",
             "E5:6 F#5:2 G5:4 B5:4", "C6:4 E6:4 D6:2 C6:2 B5:4", "A5:4 D6:4 C6:2 B5:2 A5:4", "B5:8 G5:4 E5:4",
             "A5:2 C6:2 E6:4 D6:2 C6:2 B5:4", "B5:2 D#6:2 F#6:4 E6:2 D#6:2 B5:4", "E6:8 B5:2 G5:2 E5:2 B4:2"]
    s.beat(20, C="x...............", K="x...x...x...x...", H="oxoxoxoxoxoxoxox")
    s.mel("lead", 20, "B5:16", vel=0.5)
    s.bassline(20, "Em", "R:1 R:1 O:1 R:1 " * 4)
    s.pad(20, 0, 16, chord("Em", 3), 0.5)
    for i in range(11):
        bb = 21 + i
        ch = sprog[i]
        s.mel("lead", bb, space[i])
        s.bassline(bb, ch, "R:1 R:1 O:1 R:1 " * 4)
        c = chord(ch, 4)
        pat = [0, 1, 2, 1] * 4
        for st in range(16):
            m = c[pat[st] % len(c)] + (12 if st % 8 >= 4 else 0)
            s.tracks["pluck"].append((bb * 16 + st, 1, m, 0.38, {}))
        s.pad(bb, 0, 16, chord(ch, 3), 0.35)
        if bb < 31:
            s.beat(bb, K="x...x...x...x...", S="....x.......x...", H="oxoxoxoxoxoxoxox")
        if bb >= 29 and bb < 31:
            s.mel("harm", bb, space[i], vel=0.45, shift=-12)
            s.beat(bb, O="..x...x...x...x.")
    for bb in (21, 25, 29):
        s.beat(bb, C="x...............")
    for bb in (24, 28):
        s.beat(bb, S="............xxxx")
    s.beat(30, S="........x.x.xxxx")
    s.beat(31, C="x...............", K="x.......x.......", T="........x.x.....", M="............x.x.")

    # ================================================================ WARNING (bars 32-33)
    for bb in (32, 33):
        s.beat(bb, K="x..x....x..x....")
        s.tracks["bass"].append((bb * 16, 16, midi("E1"), 0.9, {}))
        s.tracks["arp"].append((bb * 16, 16, [midi("E4"), midi("F4"), midi("Bb4")], 0.35, {"rate": 20}))
    s.roll(33, "S", 8, 16, 0.3, 1.0)
    s.fx(33, 0, "riser", 16)

    # ================================================================ BOSS (bars 34-47), D minor
    s.beat(34, C="x...............", K="x.......x.......", L="x...............")
    s.tracks["bass"].append((34 * 16, 16, midi("D2"), 1.0, {}))
    s.tracks["arp"].append((34 * 16, 16, [midi("D3"), midi("A3"), midi("D4")], 0.7, {"rate": 60}))
    s.roll(34, "S", 12, 16, 0.5, 1.0)
    riff = ["D5:1 -:1 D5:1 -:1 F5:2 A5:2 G#5:1 A5:1 G5:2 F5:2 E5:2",
            "D5:1 -:1 D5:1 -:1 F5:2 Bb5:2 A5:2 G5:2 F5:4",
            "C5:1 -:1 C5:1 -:1 E5:2 G5:2 C6:4 Bb5:2 G5:2",
            "A5:4 C#6:4 E6:4 A5:4"]
    bprog = ["Dm", "Bb", "C", "A"]
    BOSS_BEAT = dict(K="x.x...x.x.x...x.", S="....x.......x...", H="x.x.x.x.x.x.x.x.")
    for i in range(4):
        bb = 35 + i
        s.mel("lead", bb, riff[i])
        s.bassline(bb, bprog[i], "R:2 O:2 R:2 O:2 R:2 O:2 R:2 O:2")
        for st in range(0, 16, 2):
            s.tracks["arp"].append((bb * 16 + st, 1, [root(bprog[i], 3), root(bprog[i], 3) + 7,
                                                      root(bprog[i], 4)], 0.6, {"rate": 60}))
        s.beat(bb, **BOSS_BEAT)
    s.beat(35, C="x...............")
    s.beat(37, C="x...............")
    s.beat(38, S="............xxxx")
    # bar 39: laser charge (chromatic climb), bar 40: laser fires
    s.mel("lead", 39, "D5:1 D#5:1 E5:1 F5:1 F#5:1 G5:1 G#5:1 A5:1 A#5:1 B5:1 C6:1 C#6:1 D6:4")
    s.tracks["arp"].append((39 * 16, 16, chord("Dm", 4), 0.5, {"rate": 40}))
    for i in range(16):
        s.tracks["bass"].append((39 * 16 + i, 1, midi("D2"), 0.5 + 0.5 * i / 15, {}))
    s.roll(39, "S", 0, 16, 0.2, 1.0)
    s.beat(39, K="x...x...x...x...")
    s.beat(40, C="x...............", K="x...x...x...x...", L="....x...x.......")
    s.tracks["bass"].append((40 * 16, 12, midi("D1"), 1.0, {}))
    s.tracks["arp"].append((40 * 16, 12, [midi("D3"), midi("A3"), midi("D4"), midi("A4")], 0.8, {"rate": 60}))
    s.mel("lead", 40, "D6:12 C6:2 A5:2", vel=1.0)
    s.beat(40, S="............xxxx")
    # bars 41-43: RAGE - riff up an octave, doubled below, double-time drums
    RAGE_BEAT = dict(K="x.x.x.x.x.x.x.x.", S="....x.......x...", H="oooooooooooooooo")
    for i, ch in enumerate(["Dm", "Bb", "C"]):
        bb = 41 + i
        s.mel("lead", bb, riff[i], shift=12)
        s.mel("harm", bb, riff[i], vel=0.6)
        s.bassline(bb, ch, "R:2 O:2 R:2 O:2 R:2 O:2 R:2 O:2")
        s.beat(bb, C="x...............", **RAGE_BEAT)
        for st in range(0, 16, 2):
            s.tracks["arp"].append((bb * 16 + st, 1, [root(ch, 3), root(ch, 3) + 7, root(ch, 4)], 0.6,
                                    {"rate": 60}))
    s.beat(43, S="............xxxx")
    # bars 44-46: the hero theme in D major - charge, COMET BEAM, boss death
    hero_d = ["A4:2 D5:2 F#5:2 A5:6 F#5:2 A5:2", "C#6:6 B5:2 A5:4 E5:4", "D6:6 C#6:2 B5:4 F#5:4"]
    dprog = ["D", "A", "Bm"]
    for i in range(3):
        bb = 44 + i
        s.mel("lead", bb, hero_d[i])
        s.mel("harm", bb, hero_d[i], vel=0.55, shift=-12)
        s.bassline(bb, dprog[i], "R:2 O:2 R:2 O:2 R:2 O:2 R:2 O:2")
        s.pad(bb, 0, 16, chord(dprog[i], 3), 0.7)
        for st in (2, 6, 10, 14):
            s.stab(bb, st, 1.5, dprog[i], 4, 0.7)
    s.roll(44, "S", 0, 16, 0.25, 1.0)
    s.beat(44, K="x...x...x...x...")
    s.fx(44, 0, "riser", 16)
    s.beat(45, C="x...............", K="x...x...x...x...", S="....x.......x...", H="x.x.x.x.x.x.x.x.")
    s.beat(46, C="x...............", K="x.x.x.x.x.x.x.x.", S="....x.......x...", T="........x.x.....",
           M="............x.x.")
    # bar 47: silence for the mega blast, then the freed Star Core shimmers
    s.pad(47, 8, 8, chord("Dmaj9", 4), 0.8, attack=0.4, release=1.2)
    for i, nm in enumerate(("A6", "F#6", "D6", "A5")):
        s.tracks["bell"].append((47 * 16 + 8 + 2 * i, 2, midi(nm), 0.7, {}))

    # ================================================================ VICTORY (bars 48-51), D major
    s.mel("lead", 48, "D5:1 F#5:1 A5:1 D6:5 A5:2 D6:2 F#6:4")
    s.mel("harm", 48, "A4:1 D5:1 F#5:1 A5:5 F#5:2 A5:2 D6:4", vel=0.55)
    s.mel("bass", 48, "D2:4 D2:2 A1:2 D2:4 F#2:2 A2:2")
    s.beat(48, C="x...............", K="x.......x.......", S="....x.......x.x.", H="o.o.o.o.o.o.o.o.")
    s.pad(48, 0, 16, chord("D", 4), 0.6)
    s.mel("lead", 49, "G5:2 B5:2 D6:4 A5:2 C#6:2 E6:4")
    s.mel("harm", 49, "D5:2 G5:2 B5:4 E5:2 A5:2 C#6:4", vel=0.55)
    s.mel("bass", 49, "G1:2 G2:2 G1:2 G2:2 A1:2 A2:2 A1:2 A2:2")
    s.mel("lead", 50, "F#6:4 D6:2 A5:2 B5:4 D6:4")
    s.mel("harm", 50, "A5:4 F#5:2 D5:2 F#5:4 B5:4", vel=0.55)
    s.mel("bass", 50, "D2:2 D3:2 D2:2 D3:2 B1:2 B2:2 B1:2 B2:2")
    for bb, chs in ((49, ("G", "A")), (50, ("D", "Bm"))):
        s.beat(bb, K="x.....x.x.......", S="....x.......x...", H="o.x.o.x.o.x.o.x.")
        for j, ch in enumerate(chs):
            for st in (2, 6):
                s.stab(bb, j * 8 + st, 1.5, ch, 4, 0.7)
    s.mel("lead", 51, "G5:2 A5:2 B5:2 C#6:2 D6:1 E6:1 F#6:1 G6:1 A6:4")
    s.mel("bass", 51, "G1:4 G1:4 A1:4 A1:4")
    s.roll(51, "S", 0, 16, 0.3, 1.0)
    s.beat(51, K="x...x...x...x...")
    s.fx(51, 0, "riser", 16)

    # ================================================================ ENDING (bars 52-60), C major
    s.pad(52, 0, 16, chord("G7", 3), 0.55, attack=0.5)
    for i, nm in enumerate(("G5", "B5", "D6", "F6", "G6", "F6", "D6", "B5")):
        s.tracks["bell"].append((52 * 16 + 2 * i, 2, midi(nm), 0.35 + 0.05 * i, {}))
    s.tracks["bass"].append((52 * 16, 16, midi("G1"), 0.6, {}))
    s.roll(52, "H", 0, 16, 0.2, 0.8, every=2)
    s.roll(52, "S", 12, 16, 0.4, 1.0)
    ending = ["G4:2 C5:2 E5:2 G5:6 E5:2 G5:2", "B5:6 A5:2 G5:4 D5:4", "C6:6 B5:2 A5:4 E5:4",
              "F5:4 G5:2 A5:2 G5:8", "G4:2 C5:2 E5:2 G5:6 E5:2 G5:2", "B5:6 D6:2 B5:4 G5:4",
              "C6:4 A5:4 B5:4 D6:4"]
    eprog = ["C", "G", "Am", "F", "C", "G", None]
    for i in range(7):
        bb = 53 + i
        s.mel("lead", bb, ending[i])
        s.mel("harm", bb, ending[i], vel=0.5, shift=-12)
        s.beat(bb, **GROOVE)
        if eprog[i]:
            s.bassline(bb, eprog[i], "R:2 O:2 R:2 O:2 R:2 O:2 R:2 O:2")
            s.pad(bb, 0, 16, chord(eprog[i], 3), 0.5)
            for st in (2, 6, 10, 14):
                s.stab(bb, st, 1.5, eprog[i], 4, 0.65)
        else:
            s.bassline(bb, "F", "R:2 O:2 R:2 O:2")
            s.tracks["bass"] += [(bb * 16 + 8, 2, midi("G2"), 1.0, {}), (bb * 16 + 10, 2, midi("G3"), 1.0, {}),
                                 (bb * 16 + 12, 2, midi("G2"), 1.0, {}), (bb * 16 + 14, 2, midi("G3"), 1.0, {})]
            s.pad(bb, 0, 8, chord("F", 3), 0.5)
            s.pad(bb, 8, 8, chord("G", 3), 0.5)
            for st, ch in ((2, "F"), (6, "F"), (10, "G"), (14, "G")):
                s.stab(bb, st, 1.5, ch, 4, 0.65)
    for bb in (53, 57):
        s.beat(bb, C="x...............")
    s.beat(56, S="............xxxx")
    s.beat(59, S="........x.x.xxxx", T="............x...", M=".............x..", L="..............x.")
    # bar 60: the final chord rings out while the tube switches off
    s.mel("lead", 60, "C6:12", vel=1.0)
    s.mel("harm", 60, "C5:12", vel=0.5)
    s.tracks["bass"].append((60 * 16, 12, midi("C2"), 1.0, {}))
    s.pad(60, 0, 12, chord("C", 3) + [midi("C5")], 0.8, release=1.2)
    s.stab(60, 0, 10, "C", 5, 0.8)
    s.beat(60, C="x...............", K="x...............")
    for i, nm in enumerate(("C6", "E6", "G6", "C7")):
        s.tracks["bell"].append((60 * 16 + i, 4, midi(nm), 0.5, {}))
    return s
