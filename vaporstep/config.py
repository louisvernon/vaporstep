from __future__ import annotations

# Hand and lower-body input use different horizontal playfields. Hands get a
# deliberately wider range because lateral arm movement is comfortable and
# visually magnified by being closer to a laptop camera.
HAND_PLAYFIELD_LEFT = 0.14
HAND_PLAYFIELD_RIGHT = 0.86
FOOT_PLAYFIELD_LEFT = 0.18
FOOT_PLAYFIELD_RIGHT = 0.82
LANE_COUNT = 4

# A lane change must move this far beyond a boundary before switching.
# This is intentionally tiny; calibration exposes reach, not boundary hysteresis.
LANE_HYSTERESIS = 0.012

# Make the two outside lanes a little easier to enter without changing the
# center 2↔3 transition. This is expressed as a fraction of one nominal lane
# width: 0.10 shifts the 1↔2 and 3↔4 boundaries inward by 10% of a lane.
OUTER_LANE_ASSIST = 0.10

# Extend only the physical outside edge of lanes 1 and 4. Interior lane
# transitions stay exactly where OUTER_LANE_ASSIST places them; this simply
# gives a free limb a little more room when reaching around an active hold.
# Expressed as a fraction of one nominal lane width.
OUTER_LANE_EDGE_EXTENSION = 0.15

# Mild horizontal digital zoom around camera center. This reduces the physical
# side-to-side travel needed to reach the outer lanes while keeping the same
# four-lane layout. The silhouette is rendered with the same crop/zoom.
PLAYER_HORIZONTAL_ZOOM = 1.10

# Lane membership is mostly horizontal, but the rendered playfield narrows
# toward the central vanishing region. Apply only part of that visual
# perspective to tracking so a tracked limb point that visibly sits in a tapered lane
# is more likely to resolve to that lane without making controls feel warped.
# 0.0 = old fixed-width horizontal mapping; 1.0 = literal rendered perspective.
LANE_PERSPECTIVE_STRENGTH = 0.45

# Lower-body lane position uses a virtual point part-way down the shin rather
# than the knee itself. Ankle influence follows MediaPipe confidence instead of
# camera-edge position so a confidently estimated ankle can still help when it
# is near or slightly beyond the visible frame. Only the ankle contribution
# weight is smoothed; the resulting x/y position follows each pose sample
# directly so fast lateral steps are not delayed. Stomp timing uses the raw knee.
LOWER_BODY_ANKLE_BLEND = 0.55
LOWER_BODY_ANKLE_CONFIDENCE_LOW = 0.25
LOWER_BODY_ANKLE_CONFIDENCE_HIGH = 0.70
LOWER_BODY_WEIGHT_SMOOTH_ALPHA = 0.35

LANDMARK_VISIBILITY_THRESHOLD = 0.45

CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
CAMERA_FPS = 30

WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 720
TARGET_FPS = 60

# Beats of notes visible ahead on the perspective playfield.
# At 120 BPM, 8 beats is 4 seconds. Because rendering is beat-relative,
# higher-BPM
# sections traverse the field faster, matching beat-relative scrolling.
LOOKAHEAD_BEATS = 8.0

# Fallback only for synthetic/demo notes that do not carry a source beat.
LOOKAHEAD_SECONDS = 4.0
# Basic occupancy hits are deliberately much tighter than timing-bonus motion.
# The player must still occupy the lane at the beat (or within a very short
# recent/late grace), preventing a quick sweep through several lanes from
# latching many notes.
HIT_WINDOW_SECONDS = 0.10
OCCUPANCY_GRACE_SECONDS = 0.10
HIT_FLASH_SECONDS = 0.38

# Screen-space geometry for the split vector playfield. Notes emerge from a
# shared central vanishing region and travel outward to clear receptor lines.
VANISH_Y = 0.50
HAND_HIT_Y = 0.10
FOOT_HIT_Y = 0.90
VANISH_HALF_WIDTH = 0.055
