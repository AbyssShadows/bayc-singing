"""fartsynth.py: pitched farts from a source-filter model, so they can play a tune. numpy only.

A fart is a flow-driven valve (like a brass player's lips or the vocal folds, but slack and wet):
  source   a train of asymmetric flow pulses whose rate is the pitch; each cycle gets its own
           period (jitter), size (shimmer) and open time, with optional period doubling (rattle),
           a pitch scoop at the onset, a sag over the note, a slow flutter, and for long ones a
           "motorboat" ending where the pulses slow down until you hear single pops
  noise    turbulence gated by the open valve, plus a burst at the onset
  filter   a few broad resonances of the tube behind it (applied per note in the frequency domain)

Song files carry the part next to the vocal melody (same bpm and t0, so they stay in step):
  "farts": {"notes": [[midi, beats, "style"?, loudness?], ...],   midi <= 0 is a rest
            "bend":  [[startBeat, endBeat], ...]}                  deep bend-over sections (beats from t0)
Styles: toot (short), parp (a beat), long, rip (long, wet, motorboat ending), squeak, blart.

    python fartsynth.py song.json out_stem [--voice voice.wav]
writes out_stem.farts.wav (mono), out_stem.farts.json (events and a 200 Hz level envelope) and,
with --voice, out_stem.mix.wav (stereo: the voice a little right, the farts a little left).
"""
import json
import math
import os
import sys
import wave

import numpy as np

FS = 48000

STYLES = {
    # jitter/shimmer: per-cycle randomness; oq: fraction of the cycle the valve is open;
    # double: period doubling 0..1; noise/burst: turbulence and onset burst; scoop/sag: semitones;
    # flutter: (Hz, semitones); tail: slow-down ending (s, 0 = none); bright: tilt of the upper end;
    # center: how much of the note's average pitch offset is removed (1 = dead on the note)
    "toot":   dict(jitter=0.020, shimmer=0.28, oq=0.44, double=0.12, noise=0.16, burst=0.5, scoop=0.8, sag=0.5, flutter=(0.0, 0.0), tail=0.0, bright=1.00, center=0.85, drift=0.10, attack=0.004, release=0.028),
    "parp":   dict(jitter=0.030, shimmer=0.30, oq=0.40, double=0.20, noise=0.20, burst=0.6, scoop=1.4, sag=1.0, flutter=(7.0, 0.20), tail=0.0, bright=0.90, center=0.85, drift=0.12, attack=0.005, release=0.040),
    "long":   dict(jitter=0.060, shimmer=0.26, oq=0.38, double=0.18, noise=0.16, burst=0.6, scoop=2.2, sag=2.2, flutter=(5.5, 0.45), tail=0.30, bright=0.85, center=0.40, drift=0.25, attack=0.006, release=0.050),
    "rip":    dict(jitter=0.075, shimmer=0.32, oq=0.36, double=0.30, noise=0.24, burst=0.9, scoop=3.0, sag=3.2, flutter=(4.5, 0.70), tail=0.45, bright=0.80, center=0.35, drift=0.30, attack=0.006, release=0.060),
    "squeak": dict(jitter=0.020, shimmer=0.10, oq=0.50, double=0.00, noise=0.05, burst=0.2, scoop=-4.0, sag=-1.5, flutter=(9.0, 0.30), tail=0.0, bright=1.25, center=0.85, drift=0.10, attack=0.008, release=0.030),
    "blart":  dict(jitter=0.090, shimmer=0.35, oq=0.34, double=0.40, noise=0.32, burst=1.0, scoop=2.5, sag=2.0, flutter=(6.0, 0.50), tail=0.20, bright=0.70, center=0.40, drift=0.30, attack=0.004, release=0.050),
}
# the tube behind the valve: resonant peaks (Hz, Q, peak gain) on top of the direct sound
RESONANCES = ((260.0, 3.0, 1.0), (720.0, 4.0, 3.4), (1500.0, 4.5, 4.0), (2800.0, 4.5, 3.0))
LEVEL_DB = -15.0       # RMS of a loudness-1 note
SQUASH = 3.2           # soft-clip level, in units of the note's RMS


def midi_hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def _smooth_noise(n, rng, tau):
    """low-passed noise (one-pole in the frequency domain), unit variance"""
    x = rng.standard_normal(n)
    f = np.fft.rfftfreq(n, 1 / FS)
    y = np.fft.irfft(np.fft.rfft(x) / (1 + 1j * f * 2 * np.pi * tau), n)
    return y / (y.std() + 1e-12)


def render_event(ev, rng):
    st = STYLES[ev["style"]]
    dur = ev["dur"]
    n = int((dur + 0.30) * FS)
    t = np.arange(n) / FS
    u = np.clip(t / max(dur, 1e-3), 0, 1)
    semis = st["scoop"] * np.exp(-t / 0.035) - st["sag"] * u ** 1.5
    if st["flutter"][0] > 0:
        semis = semis + st["flutter"][1] * np.sin(2 * np.pi * st["flutter"][0] * t + rng.uniform(0, 2 * np.pi)) * np.clip(t / 0.15, 0, 1)
    semis = semis + st["drift"] * _smooth_noise(n, rng, 0.05)
    tail = min(st["tail"], 0.4 * dur) if (st["tail"] > 0 and dur > 0.6) else 0.0
    semis = semis - st["center"] * semis[:max(1, int((dur - tail) * FS))].mean()   # keep it in tune
    f0 = ev["hz"] * 2 ** (semis / 12)
    if tail > 0:                                   # motorboat: the pulses slow to single pops
        i0 = int((dur - tail) * FS)
        f_end = rng.uniform(11.0, 16.0)
        f0[i0:] = f0[i0] * (f_end / f0[i0]) ** np.clip((t[i0:] - (dur - tail)) / tail, 0, 1)
    flow = np.zeros(n)
    pulses = []
    pos, k, end = 0.0, 0, dur * FS
    while pos < end:
        f = f0[int(pos)]
        T = max(FS / 900.0, FS / f * (1 + st["jitter"] * rng.standard_normal()))
        a = max(0.15, 1 + st["shimmer"] * rng.standard_normal())
        if st["double"] > 0 and k % 2 == 1:
            a *= 1 - st["double"] * rng.uniform(0.4, 1.0)
        oq = float(np.clip(st["oq"] * (1 + 0.12 * rng.standard_normal()), 0.18, 0.7))
        L = max(6, int(oq * FS / max(f, 0.6 * ev["hz"])))   # in the tail the pops keep their width
        i0 = int(pos)
        L = min(L, n - i0)
        phi = np.arange(L) / L
        # the valve opens slowly and slaps shut: the abrupt closure is what makes it rasp
        g = np.where(phi < 0.7, 0.5 - 0.5 * np.cos(np.pi * phi / 0.7), 1 - ((phi - 0.7) / 0.3) ** 2)
        flow[i0:i0 + L] += a * g
        pulses.append(pos / FS)
        pos += T
        k += 1
    env = np.minimum(t / st["attack"], 1.0) * np.where(t < dur, 1.0 - 0.2 * u, 0.8 * np.exp(-(t - dur) / (st["release"] / 3)))
    open_ = np.clip(flow, 0, 1.5)
    nfft = 1 << int(math.ceil(math.log2(n)))
    f = np.fft.rfftfreq(nfft, 1 / FS)
    hiss = np.fft.irfft(np.fft.rfft(rng.standard_normal(n), nfft) * (f / (f + 900.0)), nfft)[:n]   # turbulence is hissy
    x = np.diff(flow, prepend=0.0) * 6.0 + 0.03 * flow                       # radiated pressure
    x = x + st["noise"] * 0.22 * hiss * open_                                # turbulence through the open valve
    x = x + st["burst"] * 0.10 * hiss * np.exp(-t / 0.007)                   # the pop at the start
    x = x * env
    wob = 1 + 0.06 * rng.standard_normal(len(RESONANCES))
    H = np.ones(len(f), complex)
    for i, ((F, Q, gain), w) in enumerate(zip(RESONANCES, wob)):
        r = f / (F * w)
        sign = -1.0 if i % 2 else 1.0          # alternate polarity: no dead bands between the peaks
        H += sign * (gain * (st["bright"] if F > 500 else 1.0)) * (1j * r / Q) / (1 - r * r + 1j * r / Q)
    H *= 1 / (1 + 1j * f / (4200.0 * st["bright"]))                           # soft tissue eats the top
    H *= 1 / (1 + (f / 7000.0) ** 4)
    H *= (f / 45.0) ** 2 / (1 + (f / 45.0) ** 2)
    y = np.fft.irfft(np.fft.rfft(x, nfft) * H, nfft)[:n]
    body = y[:max(1, int(dur * FS))]
    y = y / (np.sqrt(np.mean(body * body)) + 1e-9)
    y = np.tanh(y / SQUASH) * SQUASH               # flesh does not do sharp peaks: louder, and raspier
    body = y[:max(1, int(dur * FS))]
    y = y / (np.sqrt(np.mean(body * body)) + 1e-9) * 10 ** (LEVEL_DB / 20) * ev.get("loud", 1.0)
    return y, pulses


def events_from_song(song):
    beat = 60.0 / song["bpm"]
    t = song.get("t0", 0.3)
    part = song["farts"]
    gate = {"toot": 0.72, "parp": 0.80, "squeak": 0.80}
    evs = []
    for item in part["notes"]:
        midi, beats = item[0], item[1]
        d = beats * beat
        if midi > 0:
            style = item[2] if len(item) > 2 and isinstance(item[2], str) else ("toot" if beats <= 0.5 else "parp" if beats <= 1.0 else "long")
            loud = float(item[3]) if len(item) > 3 else 1.0
            s = d * gate.get(style, 0.96)
            evs.append(dict(t0=round(t, 4), t1=round(t + s, 4), dur=s, midi=midi, hz=round(midi_hz(midi), 2), style=style, loud=loud, beats=beats))
        t += d
    t_first = song.get("t0", 0.3)
    bend = [[round(t_first + a * beat, 4), round(t_first + b * beat, 4)] for a, b in part.get("bend", [])]
    return evs, bend, t


def synthesize(song, seed=11):
    """-> (mono float track, info dict)"""
    rng = np.random.default_rng(seed)
    evs, bend, t_end = events_from_song(song)
    n = int((t_end + 0.6) * FS)
    out = np.zeros(n)
    for ev in evs:
        y, pulses = render_event(ev, rng)
        i0 = int(ev["t0"] * FS)
        m = min(len(y), n - i0)
        out[i0:i0 + m] += y[:m]
        ev["pulses"] = len(pulses)
        p = np.asarray(pulses)
        mid = p[(p > 0.2 * ev["dur"]) & (p < (0.8 if ev["style"] in ("toot", "parp", "squeak") else 0.5) * ev["dur"])]
        ev["hz_real"] = round(float((len(mid) - 1) / (mid[-1] - mid[0])), 2) if len(mid) > 2 else ev["hz"]   # the pitch it actually played
    peak = np.abs(out).max()
    if peak > 0.95:
        out *= 0.95 / peak
    hop = FS // 200
    k = len(out) // hop
    rms = np.sqrt((out[:k * hop].reshape(k, hop) ** 2).mean(1))
    ref = np.percentile(rms[rms > 1e-4], 95) if (rms > 1e-4).any() else 1.0
    info = dict(version=1, fs=FS, bpm=song["bpm"], t0=song.get("t0", 0.3), duration=len(out) / FS,
                events=[{k_: v for k_, v in e.items() if k_ != "dur"} for e in evs], bend=bend,
                env=dict(rate=200, values=np.round(np.clip(rms / ref, 0, 1.5), 3).tolist()))
    return out, info


def read_wav(path):
    with wave.open(path, "rb") as w:
        assert w.getsampwidth() == 2, "16-bit PCM expected"
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768.0
        ch, fs = w.getnchannels(), w.getframerate()
    return (x.reshape(-1, ch).mean(1) if ch > 1 else x), fs


def write_wav(path, x):
    """x: (n,) mono or (n, 2) stereo float in -1..1. A file that already holds exactly this sound
    is left alone (Blender keeps the song's mix open while a scene that plays it is loaded)."""
    x = np.clip(np.asarray(x), -1.0, 1.0)
    ch = 1 if x.ndim == 1 else x.shape[1]
    data = np.round(x * 32767.0).astype("<i2").tobytes()
    if os.path.exists(path):
        try:
            with wave.open(path, "rb") as w:
                same = (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (ch, 2, FS) and w.readframes(w.getnframes()) == data
        except (wave.Error, EOFError):
            same = False
        if same:
            return
    with wave.open(path, "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(FS)
        w.writeframes(data)


def mix(voice, farts, voice_gain=1.0, fart_gain=0.9):
    n = max(len(voice), len(farts))
    v = np.concatenate([voice, np.zeros(n - len(voice))]) * voice_gain
    f = np.concatenate([farts, np.zeros(n - len(farts))]) * fart_gain
    st = np.stack([0.62 * v + 0.80 * f, 0.80 * v + 0.62 * f], 1)
    peak = np.abs(st).max()
    return st * (0.92 / peak) if peak > 0.92 else st


def build(song_path, stem, voice_path=None, log=print, voice_gain=1.0):
    """voice_gain 0: a farts-only song (the mix holds the farts alone, in the same stereo spread)"""
    with open(song_path, encoding="utf-8") as fh:
        song = json.load(fh)
    if "farts" not in song:
        return None
    track, info = synthesize(song)
    write_wav(stem + ".farts.wav", track)
    info["wav"] = stem + ".farts.wav"
    if voice_path:
        v, fs = read_wav(voice_path)
        assert fs == FS, f"{voice_path}: {fs} Hz, expected {FS}"
        write_wav(stem + ".mix.wav", mix(v, track, voice_gain=voice_gain))
        info["mix"] = stem + ".mix.wav"
        info["voice"] = voice_path
    with open(stem + ".farts.json", "w", encoding="utf-8") as fh:
        json.dump(info, fh)
    log(f"farts: {len(info['events'])} notes over {info['duration']:.1f} s -> {stem}.farts.wav" + (f", mixed with the voice -> {stem}.mix.wav" if voice_path else ""))
    return info


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) < 2:
        sys.exit(__doc__)
    build(a[0], a[1], a[a.index("--voice") + 1] if "--voice" in a else None)
