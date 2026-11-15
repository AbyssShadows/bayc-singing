//! `chimera render blender <in.json> <out> [male|female|child] [--rate 200]`
//!
//! Sings a melody file exactly like `render notes` (same planning, same source settings, same
//! sound) and writes, next to `<out>.wav`, a performance track `<out>.track.json` for animating
//! a character's face and body in sync (the BAYC Blender rig):
//!
//! - `frames`: one row per `1/rate` s (frame i = the voice's state at sample i·hop, frame 0
//!   before any sound): the 17 articulators (`keys`, template cm unless noted) followed by the
//!   telemetry scalars (`scalars`). Interval values (outRms, mouthP) cover the hop before the row.
//! - `segments`: the planner's timed phones `{ipa, t0, t1, stress?, kind}` (s from WAV sample 0).
//! - `notes` / `rests`: the melody on the same clock, one entry per note with its syllable.
//!
//! The melody file may also carry `"source": {SourcePatch}` overrides (e.g. vibratoDepth,
//! breathiness, tension, pressure) on top of the `render notes` defaults.

use crate::render::g2p;
use crate::{Ctx, FS, arg, body, wav_name};
use chimera::anatomy::geom::Vec2;
use chimera::anatomy::human::ArticKey;
use chimera::control::articulators::ARTIC_SPECS;
use chimera::math::{js_max, js_round};
use chimera::phonetics::PlannedSegment;
use chimera::phonetics::sing::{SongOptions, SungNote, midi_to_hz, plan_song};
use chimera::phonetics::syllables::lyrics_to_syllables;
use chimera::voice::human_voice::{HumanVoice, SourcePatch, VoiceTelemetry};

const CM_H2O: f64 = 980.665;
const SCALARS: [&str; 13] = [
    "f0", "voicing", "gate", "pLung", "outRms", "effort", "mouthP", "velumPort", "lipArea",
    "contactTip", "contactBody", "noiseLevel", "noiseNode",
];

fn round4(x: f64) -> f64 {
    if x.is_finite() { js_round(x * 1e4) / 1e4 } else { 0.0 }
}

fn round3(x: f64) -> f64 {
    if x.is_finite() { js_round(x * 1e3) / 1e3 } else { 0.0 }
}

fn pts(p: &[Vec2]) -> Vec<[f64; 2]> {
    p.iter().map(|q| [round3(q.x), round3(q.y)]).collect()
}

/// One video frame of the vocal tract's geometry (body cm, x forward, y up, glottis region at
/// the origin), as the app's anatomy views draw it, plus the vocal-fold scope and sound levels.
/// `t` is the telemetry of the most recent row (taken at most one row hop earlier).
fn geom_snap(v: &HumanVoice, t: &VoiceTelemetry) -> serde_json::Value {
    let Some(f) = v.airway.frame.as_ref() else { return serde_json::Value::Null };
    let grid: Vec<[f64; 6]> = f
        .grid
        .iter()
        .map(|g| [round3(g.inner.x), round3(g.inner.y), round3(g.outer.x), round3(g.outer.y), round3(g.area), g.region as f64])
        .collect();
    let step = (t.glottal_area.len() / 32).max(1);
    let scope: Vec<f64> = t.glottal_area.iter().step_by(step).take(32).map(|x| round4(*x as f64)).collect();
    let p_rms: Vec<f64> = t.pressure_rms.iter().map(|x| round3(*x as f64 / CM_H2O)).collect();
    serde_json::json!({
        "t": round4(v.clock),
        "outer": pts(&f.outer), "inner": pts(&f.inner), "tongue": pts(&f.tongue), "velum": pts(&f.velum),
        "upperLip": pts(&f.upper_lip), "lowerLip": pts(&f.lower_lip),
        "upperTeeth": pts(&f.upper_teeth), "lowerTeeth": pts(&f.lower_teeth),
        "jaw": pts(&f.jaw_bone), "epiglottis": pts(&f.epiglottis), "nasal": pts(&f.nasal_cavity),
        "glottis": [round3(f.glottis.x), round3(f.glottis.y)],
        "tip": [round3(f.tip.x), round3(f.tip.y)],
        "tongueCenter": [round3(f.tongue_center.x), round3(f.tongue_center.y)],
        "grid": grid, "split": f.split_index,
        "gScope": scope, "pRms": p_rms,
        "f0": round3(t.f0), "voicing": round3(t.voicing), "outRms": round4(t.out_rms),
        "larynx": round4(v.artic.x.larynx), "velumPort": round4(f.velum_port),
    })
}

/// One row: the articulators, then the telemetry scalars (see `SCALARS`).
fn row(v: &mut HumanVoice, t: &mut VoiceTelemetry) -> Vec<f64> {
    v.telemetry(t); // also resets the RMS accumulators, so interval values cover one hop
    let mut r: Vec<f64> = ArticKey::ALL.iter().map(|k| round4(v.artic.x.get(*k))).collect();
    let n = t.ph_areas.len() + t.or_areas.len();
    // pressure behind the lips, as the app's cheek-puff heuristic reads it (expression.ts)
    let mouth_p = if n >= 3 && n - 3 >= t.ph_areas.len() && n - 3 < t.pressure_rms.len() {
        t.pressure_rms[n - 3] as f64 / CM_H2O
    } else {
        0.0
    };
    let lip_area = v.airway.frame.as_ref().map_or(0.0, |f| f.lip_area);
    r.extend(
        [
            t.f0,
            t.voicing,
            t.gate,
            t.p_lung,
            t.out_rms,
            v.glottis.params.effort,
            mouth_p,
            t.velum_port,
            lip_area,
            v.airway.tract.contact_tip,
            v.airway.tract.contact_body,
            t.noise_level,
            t.noise_node as f64,
        ]
        .map(round4),
    );
    r
}

pub fn render(ctx: &Ctx, a: &[String]) -> Result<(), String> {
    let usage = "render blender <in.json> <out> [male|female|child] [--rate hz] [--geom-fps fps]";
    let mut rate = 200usize;
    let mut geom_fps = 30usize;
    let mut rest = Vec::new();
    let mut it = a.iter();
    while let Some(x) = it.next() {
        if x == "--rate" {
            rate = it.next().and_then(|s| s.parse().ok()).ok_or("--rate needs a whole number of Hz")?;
        } else if x == "--geom-fps" {
            geom_fps = it.next().and_then(|s| s.parse().ok()).ok_or("--geom-fps needs a whole number")?;
        } else {
            rest.push(x.clone());
        }
    }
    if rate == 0 || FS as usize % rate != 0 {
        return Err(format!("--rate must divide {FS} evenly"));
    }
    if geom_fps == 0 || FS as usize % geom_fps != 0 {
        return Err(format!("--geom-fps must divide {FS} evenly"));
    }
    let a = &rest[..];
    let input = a.first().ok_or(usage)?;
    let stem = arg(a, 1, "out/blender");
    let stem = stem.strip_suffix(".wav").unwrap_or(stem);
    let out_wav = wav_name(stem);
    let out_track = format!("{stem}.track.json");
    let body_name = arg(a, 2, "male");
    let b = body(body_name)?;

    // --- the melody, planned exactly as `render notes` does (render.rs) ---
    let text = std::fs::read_to_string(input).map_err(|e| format!("{input}: {e}"))?;
    let j: serde_json::Value = serde_json::from_str(&text).map_err(|e| format!("{input}: {e}"))?;
    let bpm = j["bpm"].as_f64().ok_or("bpm missing")?;
    let vibrato = j["vibrato"].as_f64().unwrap_or(35.0);
    let t0 = j["t0"].as_f64().unwrap_or(0.3);
    let raw: Vec<[f64; 2]> = serde_json::from_value(j["notes"].clone()).map_err(|e| format!("notes: {e}"))?;
    let g = g2p()?;
    let syl = lyrics_to_syllables(j["lyrics"].as_str().ok_or("lyrics missing")?, &g);
    let sounding = raw.iter().filter(|n| n[0] > 0.0).count();
    if syl.len() != sounding {
        return Err(format!(
            "{} syllables for {sounding} notes: {}",
            syl.len(),
            syl.iter().map(|s| s.text.as_str()).collect::<Vec<_>>().join(" ")
        ));
    }
    let beat = 60.0 / bpm;
    let mut v = HumanVoice::new(FS, b, 2);
    let first = raw.iter().find(|n| n[0] > 0.0).ok_or("no notes")?;
    v.set_source(&SourcePatch {
        f0: Some(midi_to_hz(first[0])),
        voiced: Some(true),
        pressure: Some(9.0),
        tension: Some(0.55),
        ..Default::default()
    });
    if !j["source"].is_null() {
        let extra: SourcePatch = serde_json::from_value(j["source"].clone()).map_err(|e| format!("source: {e}"))?;
        v.set_source(&extra);
    }

    let mut segments: Vec<PlannedSegment> = Vec::new();
    let mut notes_out = Vec::new();
    let mut rests_out = Vec::new();
    let (mut t, mut k, mut end) = (t0, 0usize, 0.0f64);
    let mut phrase: Vec<SungNote> = Vec::new();
    let mut start = t;
    let mut flush = |phrase: &mut Vec<SungNote>, start: f64, v: &mut HumanVoice, end: &mut f64| {
        if phrase.is_empty() {
            return;
        }
        let plan = plan_song(phrase, &SongOptions { body: body_name.into(), bpm, t0: start, vibrato });
        v.schedule(&plan.gestures); // absolute voice-clock times: the clock is 0 at WAV sample 0
        *end = js_max(*end, plan.end);
        segments.extend(plan.segments);
        phrase.clear();
    };
    for n in &raw {
        let (n0, n1) = (t, t + n[1] * beat);
        if n[0] > 0.0 {
            if phrase.is_empty() {
                start = t;
            }
            notes_out.push(serde_json::json!({
                "t0": round4(n0), "t1": round4(n1), "midi": n[0], "beats": n[1], "syl": syl[k].text,
            }));
            phrase.push(SungNote { midi: n[0], beats: n[1], syl: syl[k].clone() });
            k += 1;
        } else {
            rests_out.push(serde_json::json!({"t0": round4(n0), "t1": round4(n1), "beats": n[1]}));
            flush(&mut phrase, start, &mut v, &mut end);
        }
        t = n1;
    }
    flush(&mut phrase, start, &mut v, &mut end);
    if v.score.dropped > 0 {
        return Err(format!("score full: {} gestures dropped; split the song", v.score.dropped));
    }

    // --- render, sampling a row every hop (rendering is per sample: chunking does not change the sound) ---
    let hop = FS as usize / rate;
    let ghop = FS as usize / geom_fps;
    let n = js_round(FS * (end + 0.4)) as usize;
    let mut out = vec![0f32; n];
    let mut tele = VoiceTelemetry::default();
    let mut frames = vec![row(&mut v, &mut tele)];
    let mut geo = vec![geom_snap(&v, &tele)];
    let (mut pos, mut next_row, mut next_geo) = (0usize, hop, ghop);
    while pos < n {
        let e = n.min(next_row).min(next_geo);
        for block in out[pos..e].chunks_mut(128) {
            v.render(block);
        }
        pos = e;
        if pos == next_row {
            frames.push(row(&mut v, &mut tele));
            next_row += hop;
        }
        if pos == next_geo {
            geo.push(geom_snap(&v, &tele));
            next_geo += ghop;
        }
    }
    ctx.write_wav(&out_wav, &out)?;
    let out_geom = format!("{stem}.geom.json");
    let gj = serde_json::json!({"version": 1, "fps": geom_fps, "hop": ghop, "body": body_name, "frames": geo});
    std::fs::write(&out_geom, gj.to_string()).map_err(|e| format!("{out_geom}: {e}"))?;

    let specs: Vec<[f64; 3]> = ARTIC_SPECS.iter().map(|s| [s.min, s.max, s.hz]).collect();
    let track = serde_json::json!({
        "version": 1,
        "rate": rate,
        "sampleRate": FS,
        "hop": hop,
        "body": body_name,
        "bpm": bpm,
        "t0": t0,
        "vibrato": vibrato,
        "duration": n as f64 / FS,
        "keys": ArticKey::NAMES,
        "specs": specs,
        "scalars": SCALARS,
        "frames": frames,
        "segments": segments,
        "notes": notes_out,
        "rests": rests_out,
        "lyrics": j["lyrics"],
    });
    std::fs::write(&out_track, track.to_string()).map_err(|e| format!("{out_track}: {e}"))?;
    println!(
        "{out_wav}: {:.2} s, {sounding} notes, {} phones; {out_track}: {} rows at {rate} Hz",
        n as f64 / FS,
        segments.len(),
        frames.len()
    );
    Ok(())
}
