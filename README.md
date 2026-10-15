# RitoPaint

A transparent overlay for League of Legends replays. Draw on the
map and the marks stay pinned to the ground as the camera pans.

# Vid Link: 
https://www.youtube.com/watch?v=MNPSYVdPsBc

## What it works with

- League of Legends **replays**. The camera pose comes from the Replay API,
  which only serves during replay playback, so live games are out of scope.
- **Windows only** — the window lookup, always-on-top and click-through are all
  Win32 calls.
- League in **Windowed** mode, at any display scale. The overlay tracks the
  gameplay window's client area, so it lines up with the rendered view rather
  than with the screen.
- A single monitor. The DPI conversion is read off the primary screen, so League
  on a second display at a different scale will not line up.
- Any window size. The overlay measures League's client area at startup and
  builds the camera model from it, so no resolution is baked in — 1280x800
  places marks exactly where 3840x2400 does. The camera's vertical field of
  view is baked in, at 40 degrees, calibrated on a 16:10 window. Other aspect
  ratios are handled by widening the view horizontally, which is the usual
  convention but has not been checked against the game.

## Requirements

- Windows
- Python 3.10+
- League of Legends with the Replay API enabled (it serves on `https://127.0.0.1:2999`)
- **League set to Windowed or Borderless, not Fullscreen** — in exclusive
  fullscreen the game has no drawable window for the overlay to align to. Its
  window reports 2x2 and the overlay ends up 1 pixel wide, or 0 and it crashes.

## Install

```
pip install -r requirements.txt
```

### Enable the Replay API

It is off by default, and every `/replay/*` endpoint returns `Not Found` until
it is on. With League **fully closed** — the client rewrites this file when it
exits, so an edit made while it is running gets thrown away:

```
python enable_replay_api.py
```

That sets `EnableReplayApi=1` under `[General]` in
`C:\Riot Games\League of Legends\Config\game.cfg`. Verify it took:

```
curl -k https://127.0.0.1:2999/replay/render
```

with a replay playing — camera JSON means it is working. No Riot developer key
is involved: this is a local server inside the game process, not the public web
API at `api.riotgames.com`, and it needs no auth.

## Run

Load a replay and start playback in **windowed** mode, then:

```
python draw_overlay.py
```

It prints the rect it aligned to. That should match League's window - if it
prints your full screen size, or a 1x1, no gameplay window was found. 

The overlay starts click-through, so League stays fully usable until you switch
to draw mode.

Switch to another app and the strokes and brush dock hide; switch back to League
and they return where they were. The hotkeys are ignored while they're hidden.

## Controls

| key | |
|---|---|
| `` ` `` | toggle draw mode / click-through |
| `.` | toggle the brush dock |
| click + drag | draw a stroke |
| wheel | brush size (dock open) |
| `ctrl+shift+q` | quit the overlay |

The brush dock is a small floating panel: an HSV wheel with a brightness bar,
six quick-pick swatches, and a size slider with a live preview dot. Drag it by
its edge to move it. Clicks land on the dock without pulling focus off the
game; clicks anywhere else pass through exactly as before.

## Troubleshooting

| symptom | cause |
|---|---|
| `/replay/*` returns `Not Found` | `EnableReplayApi=1` missing from `game.cfg` — see Install. Also 404s while no replay is loaded |
| marks don't stay pinned to the map | no camera samples, so the projector never updates — check `/replay/render` first |
| overlay is 1 pixel wide, or `ZeroDivisionError` in `GroundPlaneProjector` | League is in exclusive fullscreen, where its window reports 2x2. Switch to Windowed |
| overlay lands on the wrong window | `find_window` takes the first title match in z-order. It looks for `League of Legends (TM) Client`, which is unique to `League of Legends.exe`; the launcher is `League of Legends` |
| `Terrain heights unavailable, drawing on a flat map` at startup | `Map11.wad.client` was not found under a known League install, or a patch changed the navigation grid layout. Marks still work, but drift on the river and base ramps |
| overlay does not follow League after you move or resize it | the rect is computed once, at startup. Restart the overlay |
| marks sit too far left and right, or too close in, on a 16:9 or ultrawide window | `LEAGUE_VFOV_DEG` in `calculations.py` was calibrated at 16:10. Only the horizontal half-angle comes from your aspect ratio; the vertical one is fixed. Adjust the constant until a mark holds still |
| marks drift when the observer camera tilts or changes zoom level | only `cameraPosition` is read live. `OBSERVER_PITCH_DEG` and `LEAGUE_VFOV_DEG` are constants, though `/replay/render` does serve `cameraRotation` and `fieldOfView` |

## Files

| | |
|---|---|
| `draw_overlay.py` | the overlay window — input, painting, hotkeys |
| `dock.py` | the floating brush dock — color wheel, swatches, size |
| `calculations.py` | `GroundPlaneProjector`: pixel ⇄ ground conversion, against the real terrain |
| `terrain.py` | Summoner's Rift ground heights, read from the navigation grid in `Map11.wad.client` |
| `camera_feed.py` | background camera poller, timestamped and extrapolated |
| `window_helper.py` | locates League's client area, toggles native click-through |
| `enable_replay_api.py` | one-time setup: switches on League's Replay API |
