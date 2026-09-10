# Custom VaporStep characters

VaporStep custom characters are a single rigged SVG file. The built-in procedural character remains available and does not depend on an external asset.

VaporStep installs an editable `reference-robot.svg` into `~/VaporStep/Characters/` the first time the character renderer is created. If you edit or replace that file, VaporStep does not overwrite it on later launches. The canonical repository copy at [`../../assets/characters/reference-robot.svg`](../../assets/characters/reference-robot.svg) is the authoring template.

## Make a character

1. Open `~/VaporStep/Characters/reference-robot.svg` in Inkscape, Illustrator, Affinity Designer, or another SVG editor.
2. Save a copy under a new `.svg` filename if you want to keep the reference robot too.
3. Replace the shapes inside the named artwork groups (`head`, `torso`, `left-upper-arm`, and so on) with your own art. Keep the group IDs unchanged.
4. Move the visible anchor circles so they sit on your character's joints. Keep every `anchor-*` ID unchanged and edit the circles with `cx`/`cy` coordinates rather than applying a transform to the circle itself.
5. Save as plain SVG in `~/VaporStep/Characters/`.

Characters are drawn directly over the playfield, so **outline-first artwork is strongly recommended**. Thin, dim strokes preserve note visibility much better than large opaque shapes. The reference robot intentionally demonstrates this style: its main outlines are about `0.4` SVG units wide at a 600-unit viewBox, use roughly 48% opacity, avoid dense overlapping interior outlines, and add only an extremely faint purple fill for body presence. Small filled accents are fine where they do not obscure gameplay.

In **Calibration**, press **V** to cycle through:

`Silhouette → built-in Character → each SVG in ~/VaporStep/Characters (alphabetically) → Silhouette`

The selected SVG filename is reflected in the calibration controls as soon as you cycle. VaporStep rescans the directory when you cycle, so newly added files can be picked up without a special `active.svg` filename.

## Version 1 rig

Required artwork groups:

- `head`
- `torso`
- `left-upper-arm`, `left-lower-arm`
- `right-upper-arm`, `right-lower-arm`
- `left-upper-leg`, `left-lower-leg`
- `right-upper-leg`, `right-lower-leg`

Optional artwork groups:

- `left-hand`, `right-hand`
- `left-shoe`, `right-shoe`

Required anchor circles:

- `anchor-left-ear`, `anchor-right-ear`
- `anchor-left-shoulder`, `anchor-right-shoulder`
- `anchor-left-elbow`, `anchor-right-elbow`
- `anchor-left-wrist`, `anchor-right-wrist`
- `anchor-left-hip`, `anchor-right-hip`
- `anchor-left-knee`, `anchor-right-knee`
- `anchor-left-ankle`, `anchor-right-ankle`
- `anchor-left-toe`, `anchor-right-toe`

Optional hand-orientation anchors:

- `anchor-left-hand-tip`
- `anchor-right-hand-tip`

These define the direction the hand artwork points in the source SVG, from wrist to hand-tip. At runtime VaporStep rotates the hand toward the midpoint of MediaPipe's index and pinky landmarks. If the orientation anchor is absent, older v1 characters remain compatible and VaporStep assumes the hand artwork points downward from the wrist.

The SVG root must contain `data-vaporstep-version="1"`. `data-vaporstep-name` is optional metadata for the character file.

## How rendering works

The SVG is an authoring/import format, but the artwork stays vector all the way to the final screen draw.

When a character is selected, VaporStep parses its supported SVG shapes once into a small retained vector representation: point geometry, fills, strokes and stroke widths. Curves and circles are tessellated into vector points once at load time. No character bitmap is cached.

Every display frame:

- Upper/lower arms and legs map their vector points onto the same tracked joint pairs as the built-in character. Length follows the live joints while thickness remains tied to the camera viewport scale.
- The torso's vector points map from its four SVG shoulder/hip anchors onto the same adjusted shoulder/hip quadrilateral used by the built-in procedural torso.
- The head uses the built-in head center/size calculation (ears first, then the existing nose/shoulder fallbacks) and remains upright like the built-in head.
- Hands stay centered on wrists and rotate with the live palm/finger direction when MediaPipe exposes the index/pinky landmarks.
- Shoes follow ankle-to-toe direction using the same tracked foot-index landmarks as the built-in character.
- Only after those live transformations are calculated does Pygame rasterize the resulting polygons and lines to the screen.

The guide and rig layers in the reference SVG are authoring aids and are never part of the rendered artwork.

## SVG compatibility and safety

Version 1 intentionally supports a small SVG subset so character rendering stays predictable and cheap:

- groups
- `path` commands `M/L/H/V/C/S/Q/T/Z` (absolute or relative)
- `rect`, `circle`, `ellipse`, `line`, `polygon`, `polyline`
- solid `#RGB`, `#RRGGBB`, or `rgb()` fills and strokes
- fill/stroke opacity, overall opacity, stroke width
- basic `matrix`, `translate`, `scale`, `rotate`, `skewX`, and `skewY` transforms

Version 1 does **not** support SVG arc path commands (`A/a`), gradients/patterns, filters, embedded or external images, `<use>`, scripts, animation, linked resources, or external fonts. Unsupported files are rejected and VaporStep falls back to the built-in character instead of stopping gameplay.

Character files are also size/complexity limited. Keeping the format deliberately small means the SVG is parsed only when selected while the per-frame work is just transforming and drawing retained vector primitives.
