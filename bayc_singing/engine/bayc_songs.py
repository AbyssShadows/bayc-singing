"""bayc_songs.py: everything about the song before the synth sings it. Plain Python, no Blender.

  load_song(path)     a song file (.json) or a MIDI melody (.mid / .midi / .kar) -> song dict
  prepare(song, ...)  the options: sing / sing + farts / farts only, transposition, bend-over
  fit_notes(...)      make the notes match the lyric's syllables (merge or split notes)

Song file (.json), the same format chimera-vocal-synth reads, with two conveniences:
  {"title": "My Song", "bpm": 120, "t0": 0.5, "vibrato": 45,
   "lyrics": "hello bored ape ~",
   "notes": [["C4", 1], ["D4", 0.5], [64, 0.5], ["rest", 1], ["G4", 2], ["E4", 2]],
   "farts": {"notes": [[0, 4], ["C3", 1, "parp"], ...], "bend": [[8, 16]]}}       optional
  - a note is [pitch, beats]; pitch is a MIDI number (60 = middle C) or a name ("C4", "F#3",
    "Bb2"); 0, "rest" or "-" is a rest
  - exactly one lyric syllable per sounding note: write words normally (the synth splits them:
    wonderful = won-der-ful); hyphens force breaks in made-up words ("boo-ga-loo"),
    a lone "~" holds the previous vowel over one more note
  - farts: [pitch, beats, style?, loudness?]; styles toot, parp, long, rip, squeak, blart

Command line (any Python 3, or Blender's: blender -b --python bayc_songs.py -- ...):
  python bayc_songs.py check song.json            the notes, range and length; with the synth,
                                                 whether the syllables match the notes
  python bayc_songs.py midi in.mid out.json [--lyrics "text" | --lyrics lyrics.txt] [--track N]
"""
import json
import math
import os
import re
import struct
import subprocess
import sys
import tempfile

NAMES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
# comfortable range of each voice (MIDI): the median of the tune is moved by octaves towards `mid`
VOICES = {"male": {"lo": 43, "mid": 53, "hi": 65}, "female": {"lo": 55, "mid": 64, "hi": 77},
          "child": {"lo": 58, "mid": 67, "hi": 81}}
SCAT = ["doo", "bee", "doo", "bah", "doo", "wah", "dee", "dah"]


# ------------------------------------------------------------------------------------------------
# notes
# ------------------------------------------------------------------------------------------------
def to_midi(p):
    """60, "C4", "F#3", "Bb2", "rest", "-", 0 -> MIDI number (0 = rest)"""
    if isinstance(p, (int, float)):
        return int(round(p)) if p > 0 else 0
    s = str(p).strip()
    if s.lower() in ("", "-", "r", "rest", "x", "~"):
        return 0
    m = re.fullmatch(r"([A-Ga-g])([#b]*)(-?\d+)", s)
    if not m:
        raise ValueError(f"not a note: {p!r} (use a MIDI number like 60 or a name like C4, F#3, Bb2)")
    pc = NAMES[m.group(1).upper()] + m.group(2).count("#") - m.group(2).count("b")
    return 12 * (int(m.group(3)) + 1) + pc


def midi_name(m):
    return ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"][m % 12] + str(m // 12 - 1)


def normalize(song):
    """note names -> MIDI numbers, beats -> floats; checks the basics"""
    for k in ("bpm", "notes"):
        if k not in song:
            raise ValueError(f"the song has no \"{k}\"")
    song["notes"] = [[to_midi(n[0]), float(n[1])] for n in song["notes"]]
    if not any(m > 0 for m, _ in song["notes"]):
        raise ValueError("the song has no sounding notes")
    song.setdefault("t0", 0.5)
    song.setdefault("vibrato", 45)
    if "farts" in song:
        f = song["farts"]
        f["notes"] = [[to_midi(n[0]), float(n[1])] + list(n[2:]) for n in f["notes"]]
        f.setdefault("bend", [])
    return song


def sounding(notes):
    return [n for n in notes if n[0] > 0]


def total_beats(notes):
    return sum(b for _, b in notes)


# ------------------------------------------------------------------------------------------------
# MIDI files (format 0/1, standard or karaoke .kar): the melody line and any lyric events
# ------------------------------------------------------------------------------------------------
def _varlen(d, i):
    v = 0
    while True:
        c = d[i]
        i += 1
        v = (v << 7) | (c & 0x7F)
        if not c & 0x80:
            return v, i


def read_midi(path):
    """-> ticks per beat, tempo (us per beat), tracks: [{"notes": [(t0, t1, pitch, ch)], "text": [(t, str)], "name": str}]"""
    with open(path, "rb") as fh:
        d = fh.read()
    if d[:4] != b"MThd":
        raise ValueError(f"{path}: not a MIDI file")
    hlen, fmt, ntr, div = struct.unpack(">IHHH", d[4:14])
    if div & 0x8000:
        raise ValueError("SMPTE-timed MIDI files are not supported")
    i, tracks, tempo = 8 + hlen, [], None
    while i < len(d) and len(tracks) < ntr:
        tag, ln = d[i:i + 4], struct.unpack(">I", d[i + 4:i + 8])[0]
        i += 8
        end = i + ln
        if tag != b"MTrk":
            i = end
            continue
        t, status, on, tr = 0, 0, {}, {"notes": [], "text": [], "name": ""}
        while i < end:
            dt, i = _varlen(d, i)
            t += dt
            b = d[i]
            if b == 0xFF:
                kind = d[i + 1]
                ln2, j = _varlen(d, i + 2)
                data = d[j:j + ln2]
                i = j + ln2
                if kind == 0x51 and tempo is None:
                    tempo = int.from_bytes(data, "big")
                elif kind in (0x01, 0x05):
                    tr["text"].append((t, data.decode("latin-1")))
                elif kind == 0x03:
                    tr["name"] = data.decode("latin-1").strip()
                continue
            if b in (0xF0, 0xF7):
                ln2, j = _varlen(d, i + 1)
                i = j + ln2
                continue
            if b & 0x80:
                status = b
                i += 1
            hi, ch = status & 0xF0, status & 0x0F
            if hi in (0xC0, 0xD0):
                i += 1
                continue
            a, v = d[i], d[i + 1]
            i += 2
            if hi == 0x90 and v > 0:
                on.setdefault((a, ch), []).append(t)
            elif hi == 0x80 or (hi == 0x90 and v == 0):
                if on.get((a, ch)):
                    tr["notes"].append((on[(a, ch)].pop(0), t, a, ch))
        tracks.append(tr)
        i = end
    return div, tempo or 500000, tracks


def _melody_score(tr):
    notes = [n for n in tr["notes"] if n[3] != 9]           # channel 10 is drums
    if len(notes) < 8:
        return 0.0
    starts = sorted(n[0] for n in notes)
    mono = len(set(starts)) / len(starts)                     # chords share their start
    mean = sum(n[2] for n in notes) / len(notes)
    return len(notes) * mono ** 2 * (1.0 if 52 <= mean <= 86 else 0.35) * (1.6 if tr["text"] else 1.0)


def midi_to_song(path, track=None, grid=0.25):
    """-> song (notes on a 1/16-note grid, lyrics from karaoke/lyric events or None), info lines"""
    div, tempo, tracks = read_midi(path)
    scored = sorted(((i, _melody_score(t)) for i, t in enumerate(tracks)), key=lambda x: -x[1])
    if track is None:
        if not scored or scored[0][1] == 0:
            raise ValueError("no melody track found in the MIDI file")
        track = scored[0][0]
    if not 0 <= track < len(tracks):
        raise ValueError(f"track {track} doesn't exist (the file has tracks 0-{len(tracks) - 1})")
    tr = tracks[track]
    notes = sorted((n for n in tr["notes"] if n[3] != 9), key=lambda n: (n[0], -n[2]))
    # one line: at each start keep the highest note, and cut a note off where the next begins
    line = []
    for n in notes:
        if line and n[0] == line[-1][0]:
            continue
        if line and n[0] < line[-1][1]:
            line[-1] = (line[-1][0], n[0], line[-1][2])
        line.append((n[0], n[1], n[2]))
    q = lambda tick: round(tick / div / grid) * grid
    out, pos, at_start = [], None, []
    for t0, t1, p in line:
        a, b = q(t0), max(q(t1), q(t0) + grid)
        if pos is None:
            pos = a
        elif a > pos:
            if a - pos >= grid and out:
                out.append([0, a - pos])
            pos = a
        elif a < pos:                                          # overlapped after rounding
            a = pos
            b = max(b, a + grid)
        out.append([p, b - a])
        at_start.append(t0)
        pos = b
    bpm = round(60e6 / tempo, 2)
    # lyrics: karaoke text or lyric events, matched to the notes they start
    lyr = [(t, s) for t, s in (tr["text"] or next((x["text"] for x in tracks if len(x["text"]) > 8), []))
           if s and not s.startswith("@") and not s.startswith("%")]
    lyrics = None
    if len(lyr) >= 0.5 * len(at_start):
        tokens, k = [], 0
        for idx, t0 in enumerate(at_start):
            syl = None
            while k < len(lyr) and lyr[k][0] <= t0 + div // 8:
                syl = lyr[k][1] if syl is None else syl + lyr[k][1]
                k += 1
            if syl is None:
                tokens.append("~")                           # a note without a syllable holds the last vowel
                continue
            new_word = syl[:1] in (" ", "/", "\\") or not tokens or tokens[-1] == "~"
            clean = re.sub(r"[^A-Za-z']", "", syl)
            if not clean:
                tokens.append("~")
            elif new_word:
                tokens.append(clean)
            else:
                tokens[-1] = tokens[-1] + "-" + clean        # same word: a forced syllable break
        if tokens and tokens[0] == "~":
            tokens[0] = "oh"
        lyrics = " ".join(tokens)
    name = os.path.splitext(os.path.basename(path))[0]
    song = {"title": name, "bpm": bpm, "t0": 0.5, "vibrato": 45, "notes": out}
    if lyrics:
        song["lyrics"] = lyrics
    info = [f"MIDI: track {track}{' (' + tr['name'] + ')' if tr['name'] else ''}, {len(sounding(out))} notes, "
            f"{bpm:g} bpm, {midi_name(min(p for p, _ in sounding(out)))}-{midi_name(max(p for p, _ in sounding(out)))}"
            + ("; lyrics from the file" if lyrics else ""),
            "other tracks with notes: " + ", ".join(f"{i}" for i, s in scored[1:6] if s > 0)]
    return song, info


# ------------------------------------------------------------------------------------------------
# lyrics vs notes
# ------------------------------------------------------------------------------------------------
def scat(n):
    return " ".join(SCAT[i % len(SCAT)] for i in range(n))


def read_lyrics(text):
    """lyrics text, or a path to a .txt file with them"""
    if text and len(text) < 260 and text.lower().endswith(".txt") and os.path.exists(text):
        with open(text, encoding="utf-8") as fh:
            text = fh.read()
    return " ".join((text or "").split())


def fit_notes(notes, n_syl):
    """merge the shortest notes into their neighbours, or split the longest, until the number of
    sounding notes equals the number of syllables (the tune bends to the words)"""
    notes = [list(n) for n in notes]
    while len(sounding(notes)) > n_syl and len(sounding(notes)) > 1:
        idx = [i for i, n in enumerate(notes) if n[0] > 0]
        cand = [i for i in idx[1:] if notes[i - 1][0] > 0] or idx[1:]
        i = min(cand, key=lambda j: notes[j][1])
        prev = max(j for j in idx if j < i)
        notes[prev][1] += notes[i][1] + sum(notes[j][1] for j in range(prev + 1, i))
        del notes[prev + 1:i + 1]
    while len(sounding(notes)) < n_syl:
        i = max((j for j, n in enumerate(notes) if n[0] > 0), key=lambda j: notes[j][1])
        half = notes[i][1] / 2
        notes[i:i + 1] = [[notes[i][0], half], [notes[i][0], half]]
    return notes


def syllables(chimera, lyrics):
    """how chimera splits the lyric into syllables (it prints them when the count is wrong)"""
    with tempfile.TemporaryDirectory() as td:
        probe = os.path.join(td, "probe.json")
        with open(probe, "w", encoding="utf-8") as fh:
            json.dump({"bpm": 120, "t0": 0.2, "lyrics": lyrics, "notes": [[60, 1]] * 2000}, fh)
        r = subprocess.run([chimera, "render", "blender", probe, os.path.join(td, "x"), "male"],
                           capture_output=True, text=True)
        m = re.search(r"(\d+) syllables for \d+ notes: (.*)", r.stdout + r.stderr)
        if not m:
            raise RuntimeError("the synth didn't report the syllables: " + (r.stderr or r.stdout).strip()[:300])
        return m.group(2).split()


# ------------------------------------------------------------------------------------------------
# the options
# ------------------------------------------------------------------------------------------------
def octave_shift(notes, mid):
    s = sorted(p for p, _ in sounding(notes))
    med = s[len(s) // 2]
    return 12 * round((mid - med) / 12)


def shifted(notes, k):
    return [[p + k if p > 0 else 0, b] + list(rest) for p, b, *rest in notes]


def fart_cover(song):
    """farts only: the farts play the tune (moved by octaves to where farts carry a tune)"""
    k = octave_shift(song["notes"], 50)
    notes = shifted(song["notes"], k)
    last = max(i for i, n in enumerate(notes) if n[0] > 0)
    for n in notes:
        if 0 < n[0] < 36:
            n[0] += 12
    if notes[last][1] >= 2:
        notes[last] = [notes[last][0], notes[last][1], "rip", 1.15]
    return {"notes": notes}


def fart_gaps(song):
    """sing + farts, for a song without its own fart part: a fart in every gap of the vocal line
    (toot, parp or a long one, by the gap's length), pitched under the next sung note, and a big
    rip after the last note"""
    notes, out, pos = song["notes"], [], 0.0
    nxt = lambda i: next((n[0] for n in notes[i + 1:] if n[0] > 0), next(n[0] for n in reversed(notes) if n[0] > 0))
    for i, (p, b) in enumerate(notes):
        if p == 0 and b >= 0.5:
            q = nxt(i)
            while q > 47:
                q -= 12
            if b < 1:
                style, d = "toot", b
            elif b < 2:
                style, d = "parp", 1.0
            else:
                style, d = "long", min(b - 0.5, 3.0)
            out += [[0, pos]] if pos > 0 else []
            out.append([max(q, 36), d, style])
            pos = b - d
        else:
            pos += b
    out += [[0, pos]] if pos > 0 else []
    out.append([36, 3.0, "rip", 1.15])
    return {"notes": [n for n in out if n[1] > 0]}


def auto_bend(song):
    """a deep bend-over in the middle of the song (whole bars, 8-18 beats)"""
    L = total_beats(song["notes"])
    if L < 24:
        return []
    a = 4 * round(0.42 * L / 4)
    return [[a, a + max(8, min(18, 4 * round(0.2 * L / 4)))]]


def prepare(song, mode="sing", voice="male", transpose="auto", bend=True):
    """mode: "sing" (vocals only), "both" (sing + farts) or "farts" (farts only). transpose:
    "auto" moves the tune by octaves into the voice's range, or a number of semitones. -> song,
    info lines. The vocal line is kept in every mode: in a farts-only song it sets the timing."""
    song = normalize(json.loads(json.dumps(song)))
    info = []
    if transpose == "auto":
        k = octave_shift(song["notes"], VOICES[voice]["mid"])
    else:
        k = int(transpose)
    if k:
        song["notes"] = shifted(song["notes"], k)
        info.append(f"transposed the tune {k:+d} semitones for the {voice} voice")
    own = song.pop("farts", None)
    if mode == "both":
        song["farts"] = own if own else fart_gaps(song)
        info.append("farts: the song's own part" if own else "farts: one in every gap of the vocal line, and a rip at the end")
    elif mode == "farts":
        song["farts"] = fart_cover(song)
        info.append("farts only: the farts play the tune; he doesn't sing")
    if "farts" in song:
        if own and own.get("bend"):
            song["farts"]["bend"] = own["bend"]
        elif bend:
            song["farts"]["bend"] = auto_bend(song)
        if not bend:
            song["farts"]["bend"] = []
    s = sounding(song["notes"])
    lo, hi = min(p for p, _ in s), max(p for p, _ in s)
    v = VOICES[voice]
    if lo < v["lo"] - 2 or hi > v["hi"] + 3:
        info.append(f"note: the tune spans {midi_name(lo)}-{midi_name(hi)}; the {voice} voice is happiest in "
                    f"{midi_name(v['lo'])}-{midi_name(v['hi'])}")
    return song, info


def load_song(path, lyrics=None, track=None):
    """-> song, info lines. MIDI melodies get their lyrics from the file, from `lyrics`, or scat"""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".mid", ".midi", ".kar"):
        song, info = midi_to_song(path, track)
    else:
        try:
            with open(path, encoding="utf-8") as fh:
                song = json.load(fh)
        except (ValueError, UnicodeDecodeError) as e:
            raise ValueError(f"{os.path.basename(path)} is not a song: use a .json song file (see "
                             f"songs/template_do_re_mi.json) or a MIDI file (.mid/.midi/.kar). ({e})")
        info = []
        song.setdefault("title", os.path.splitext(os.path.basename(path))[0])
    text = read_lyrics(lyrics)
    if text:
        song["lyrics"] = text
    if not song.get("lyrics"):
        song["notes"] = [[to_midi(p), float(b)] for p, b, *_ in song["notes"]]
        song["lyrics"] = scat(len(sounding(song["notes"])))
        info.append("no lyrics: he scats (doo bee doo bah ...)")
    return song, info


def summary(song):
    s = sounding(song["notes"])
    dur = song.get("t0", 0.5) + total_beats(song["notes"]) * 60 / song["bpm"]
    lo, hi = min(p for p, _ in s), max(p for p, _ in s)
    out = f"{song.get('title', 'song')}: {len(s)} notes, {song['bpm']:g} bpm, {dur:.1f} s, {midi_name(lo)}-{midi_name(hi)}"
    if song.get("farts"):
        out += f"; fart part {len(sounding(song['farts']['notes']))} notes" + (", bend-over" if song["farts"].get("bend") else "")
    return out


def _main(argv):
    if len(argv) >= 2 and argv[0] == "check":
        song, info = load_song(argv[1])
        song = normalize(song)
        print("\n".join(info + [summary(song)]))
        chim = argv[argv.index("--chimera") + 1] if "--chimera" in argv else None
        if chim:
            syl = syllables(chim, song["lyrics"])
            n = len(sounding(song["notes"]))
            print(f"syllables {len(syl)} for {n} notes: " + ("OK" if len(syl) == n else "MISMATCH: " + " ".join(syl)))
            return 0 if len(syl) == n else 1
        return 0
    if len(argv) >= 3 and argv[0] == "midi":
        lyr = argv[argv.index("--lyrics") + 1] if "--lyrics" in argv else None
        trk = int(argv[argv.index("--track") + 1]) if "--track" in argv else None
        song, info = load_song(argv[1], lyr, trk)
        with open(argv[2], "w", encoding="utf-8") as fh:
            json.dump(song, fh, indent=1)
        print("\n".join(info + [summary(normalize(song)), f"wrote {argv[2]}"]))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    sys.exit(_main(args))
