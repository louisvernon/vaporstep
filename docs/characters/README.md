# Custom VaporStep characters

VaporStep custom characters are a single rigged SVG file. The built-in procedural character remains the default and does not depend on any external asset.

Start with [`reference-robot.svg`](reference-robot.svg). It is both a working character and an authoring template.

## Make a character

1. Download `reference-robot.svg` and open it in Inkscape, Illustrator, Affinity Designer, or another SVG editor.
2. Replace the shapes inside the named artwork groups (`head`, `torso`, `left-upper-arm`, and so on) with your own art. Keep the group IDs unchanged.
3. Move the visible anchor circles so they sit on your character's joints. Keep every `anchor-*` ID unchanged and edit the circles with `cx`/`cy` coordinates rather than applying a transform to the circle itself.
4. Save as plain SVG.
5. Put the SVG in `~/VaporStep/Characters/`.

With exactly one SVG in that directory, VaporStep uses it whenever **Character** visual mode is selected. If you keep several SVGs there, name the one you want to use `active.svg`. If several SVGs exist and none is named `active.svg`, VaporStep keeps using the built-in character.

Remove/rename `active.svg` (or remove the sole SVG) to return to the built-in character. Silhouette mode is unchanged.

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

The SVG root must contain `data-vaporstep-version="1"`. `data-vaporstep-name` is optional.

## How the rig moves

The SVG replaces the drawing only; VaporStep still owns the pose rig.

- Upper/lower arms and legs attach to the same tracked joint pairs as the built-in character. Their length follows those joints while their thickness follows camera viewport scale.
- The torso maps its four SVG shoulder/hip anchors onto the same adjusted shoulder/hip quadrilateral used by the built-in procedural torso.
- The head uses the built-in head center/size calculation (ears first, then the existing nose/shoulder fallbacks) and remains upright like the built-in head.
- Hands stay centered on wrists.
- Shoes follow ankle-to-toe direction using the same tracked foot-index landmarks as the built-in character.

The guide and rig layers in `reference-robot.svg` are authoring aids and are never rendered in game; only the named artwork groups are rasterized.

## SVG compatibility and safety

Keep character SVGs intentionally simple: vector paths/shapes, fills, strokes, simple gradients, and internal definitions. Avoid scripts, embedded/external images, animation, filters, external fonts, and linked resources.

VaporStep rasterizes each body part once when the renderer starts, then reuses those surfaces during play. External links/resources and active SVG content are rejected. Character files are also size/complexity limited. A malformed or unsupported custom SVG falls back to the built-in character instead of stopping gameplay.
