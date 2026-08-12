# RiotPaint

A transparent, always-on-top overlay for League of Legends replays. Draw on the
map and the marks stay pinned to the ground as the camera pans.

Marks are stored as **world coordinates**, not screen pixels. Every frame, each
point is re-projected through a model of the observer camera — so a circle drawn
around the dragon pit stays on the dragon pit.

## Requirements

- Windows
- Python 3.10+
- League of Legends with the Replay API enabled (it serves on `https://127.0.0.1:2999`)

## Install

```
pip install -r requirements.txt
```

## Run

Load a replay, then:

```
python draw_overlay.py
```

The overlay starts click-through, so League stays fully usable until you switch
to draw mode. Global hotkeys may require running as administrator.

## Controls

| key | |
|---|---|
| `` ` `` | toggle draw mode / click-through |
| `.` | toggle the settings panel |
| drag | draw a stroke |
| wheel | brush width (settings panel open) |

The settings panel takes any valid color name or hex code.

## Files

| | |
|---|---|
| `draw_overlay.py` | the overlay window — input, painting, hotkeys |
| `calculations.py` | `GroundPlaneProjector`: pixel ⇄ ground (y=0) conversion |
| `camera_feed.py` | background camera poller, timestamped and extrapolated |
| `window_helper.py` | locates League's client area, toggles native click-through |
