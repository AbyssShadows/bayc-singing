# Third-party notices

This project stands on other people's work. Thank you to all of them.

## chimera-vocal-synth: the singing voice

- **Author:** Jameson Hodge
- **Original repository:** https://github.com/jamesondh/chimera-vocal-synth
- **License:** MIT. The full text is in [`bayc_singing/bin/LICENSE-chimera-vocal-synth.txt`](bayc_singing/bin/LICENSE-chimera-vocal-synth.txt).

chimera is a physical-modeling voice synthesizer: it simulates a human airway (lungs, vocal folds,
throat, tongue, lips) to sing. Every singing voice in this project, and the mouth, tongue and
throat movements the animation follows, come from it.

`bayc_singing/bin/windows-x64/chimera.exe` is built from upstream commit
`eed4a5ff2695ad151df2210d012b2a4ab584f099`, with two small additions. Both are in
[`chimera-patch/`](chimera-patch/):

- `blender.rs`, a new `render blender` command. It writes the same WAV as `render notes`, plus the
  articulator and telemetry tracks that drive the animation (`.track.json` and `.geom.json`).
- `main.rs.patch`, which registers that command and lets a standalone copy of the binary find its
  dictionary next to itself.

The sound engine is not changed. These additions are offered under the same MIT license.

## CMU Pronouncing Dictionary

- **Source:** Carnegie Mellon University. chimera reads it to split lyrics into syllables and sounds.
- **File:** `bayc_singing/bin/windows-x64/data/cmudict.txt.gz`, as shipped in chimera-vocal-synth.
- **License:** BSD-style. The full text is in [`bayc_singing/bin/LICENSE-CMUdict.txt`](bayc_singing/bin/LICENSE-CMUdict.txt).

## AVHershey Simplex font

- **Author:** Stewart C. Russell (https://github.com/scruss/AVHershey-OTF). The font is derived
  from Allen V. Hershey's public-domain vector fonts (1967).
- **License:** CC0 1.0 / WTFPL. The full text is in [`bayc_singing/fonts/AVHERSHEY-LICENSE.txt`](bayc_singing/fonts/AVHERSHEY-LICENSE.txt).
- **Used for:** the lettering in the X-ray look, the same font chimera's own display uses.

## Blender

The add-on runs inside Blender (https://www.blender.org, GPL). Blender itself is not bundled.

## Trademarks

Bored Ape Yacht Club, BAYC and Bored Ape are trademarks of Yuga Labs. This project is a
community tool, not affiliated with or endorsed by Yuga Labs. It ships no ape artwork or models:
you bring your own character and use it under whatever rights you hold to it. The same goes for
Jnkyz and any other character you use it with.

## Music

The included songs are original compositions made for this project, or public-domain melodies:
Jingle Bells (James Lord Pierpont, 1857) and the Can-Can galop from Offenbach's *Orpheus in the
Underworld* (1858), with new lyrics. All are free to post. Songs and MIDI files you add are your
responsibility: a cover of a copyrighted song is not free to post just because the voice is
synthesized. See "Copyright and posting" in the README.
