# HUD tracking fixtures

25 frames from a 30 s Star Citizen flight recording (10 fps, 5120x2160
monitor, recording origin at screen (1307, 65)). Each JPEG (quality 90,
1058x826) is the area `search_area()` grabs with the default range around the
calibrated digits box `{"left": 2559, "top": 773, "width": 57, "height": 25}`:
screen x 2059..3116, y 373..1198. Files keep the recording's frame numbers.

`labels.json`:

- `box`: the calibrated digits box (screen pixels); `crop_origin`: screen
  position of crop pixel (0, 0). The box sits at (500, 400) in crop pixels.
- `frames[]`: `file`, `value` (the signature number on the plate), `pin`
  (top-left of the 24x28 pin icon, crop pixels), `note`. `value` and `pin`
  are null when no plate is visible.
- `f0160.jpg` has `"calibration": true`: the plate sits on the box; build the
  Anchor from it with `find_anchor(crop, (500, 400, 57, 25))`.

Labels were read by eye. Pin positions were placed by eye and then snapped
with a local match of the reference pin (`../signal_42000_5k2k.png`) in a
small window, and every result was checked on a 3x zoom: accurate to about
2 px (3 px on f0135, heavy tint). No tracker output was used.

Coverage: plate offsets from -217 to +265 px in x and -46 to +213 px in y
from the calibrated position; values 51000, 52000, 17020 and 80000 (80000 is
above the app's 60000 limit, so a reader should reject it); four frames with
no plate (f0010 is a hard negative with UNKNOWN marker pins and red WARNING
text); blue scan tint (f0135, f0188, f0224, f0280) and motion blur (f0204,
f0280).
