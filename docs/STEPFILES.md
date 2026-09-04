# Stepfiles and chart authoring

VaporStep reads supported StepMania-compatible `.sm` and `.ssc` song libraries. This document describes the formats VaporStep currently understands and how source-chart notes are interpreted by the game.

VaporStep does not ship music, charts, banner images or other song-pack content. Make sure you have the rights to distribute any content you create or share.

## Supported chart types

VaporStep currently supports:

- `dance-single` — four source columns
- `ds3ddx-single` — eight source columns with explicit hand/foot channels

When both `.ssc` and `.sm` files are available for a song, VaporStep prefers `.ssc`.

## `dance-single` mapping

For `dance-single` charts:

- one new note head on a row becomes a **foot target**;
- two new note heads beginning on the same row become a **hand target**;
- notes already being held do not turn a later single note into a hand target.

This lets ordinary four-column charts produce both foot and hand gameplay without requiring a custom file format.

## `ds3ddx-single` mapping

`ds3ddx-single` provides explicit foot and hand channels. VaporStep maps those channels directly to its four foot lanes and four hand lanes.

`ds3ddx-double` is currently ignored.

## Timing and scoring

Being in the correct lane is sufficient for a basic hit. A deliberate movement can improve the timing judgment:

- entering a lane can count as a timing input;
- upward wrist movement is treated as a hand strike;
- downward knee movement is treated as a foot strike.

Current timing windows are:

- **PERFECT:** ±100 ms
- **GREAT:** ±300 ms
- **basic occupancy:** ±100 ms around the note

These are gameplay tuning values, not requirements of the stepfile format, and may change as VaporStep evolves.

## Holds and rolls

Explicit holds/rolls in the source chart are rendered as sustained blocks.

The player hits the head normally, remains in the required lane, and sustains the position through the tail. A brief grace period helps with short cross-steps and tracking occlusions. If a sustain is broken, the remaining block is greyed out and does not reactivate.

## Implicit chains

VaporStep can optionally turn repeated identical targets into a sustained phrase. This is intended to avoid requiring an artificial new stomp or hand strike for every note in a dense repeated sequence.

Current automatic chain generation requires:

- at least three repeated identical targets;
- gaps of no more than two beats;
- no generated combination that would make the chart physically impossible alongside other simultaneous notes or sustains.

The timing judgment on the chain head carries through the active phrase. If the chain is broken, the remaining portion stays visible but inactive.

Implicit chains have two pre-song modes:

- **ON** — replace eligible repeated targets with generated sustained blocks;
- **OFF** — disable non-hold implicit chains.

Explicit source-chart holds remain active in both modes.

## BPM and chart timing

VaporStep uses chart timing rather than audio analysis for note movement and beat-synchronized visuals. BPM changes, stops, delays and warps are read from compatible timing data.

Scrolling is beat-relative, so faster BPM sections naturally move targets through the playfield faster.

## Assets

A song may reference music, banner and background files. VaporStep only resolves those assets from inside the song's own directory; absolute paths, path traversal and symlinks escaping that directory are rejected.

## Making charts for VaporStep

The simplest authoring path is to create a normal supported StepMania-compatible chart and test it in VaporStep.

A few practical guidelines:

- Use `dance-single` for conventional four-column material that VaporStep can reinterpret automatically.
- Use `ds3ddx-single` when you want explicit control over hand and foot channels.
- Use source holds when you explicitly want the player to sustain a position.
- Toggle Virtual Holds on and off when testing dense repeated passages to compare inferred sustained phrases with the original notes.
- Avoid designing simultaneous targets that require more limbs than a player can reasonably keep active.

Compatibility will continue to evolve, so charts intended specifically for VaporStep should be tested against the version you plan to distribute with them.
