"""
Turns on League's local Replay API by editing game.cfg.

The overlay reads the camera pose from that API, and it is off by default, so
run this once before the first launch:

    python enable_replay_api.py

League must be fully closed. The client rewrites game.cfg when it exits, so an
edit made while it is running gets thrown away.
"""
import os
import sys

CANDIDATE_PATHS = [
    r"C:\Riot Games\League of Legends\Config\game.cfg",
    os.path.expandvars(r"%LOCALAPPDATA%\Riot Games\League of Legends\Config\game.cfg"),
    os.path.expandvars(r"%PROGRAMFILES%\Riot Games\League of Legends\Config\game.cfg"),
    os.path.expandvars(r"%PROGRAMFILES(X86)%\Riot Games\League of Legends\Config\game.cfg"),
]


def find_config():
    for path in CANDIDATE_PATHS:
        if path and os.path.isfile(path):
            return path
    return None


def enable_replay_api(path):
    """Sets EnableReplayApi=1 under [General], adding either as needed."""
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    in_general = False
    found_key = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.lower() == "[general]":
            in_general = True
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            in_general = False
        if in_general and stripped.lower().startswith("enablereplayapi"):
            lines[i] = "EnableReplayApi=1\n"
            found_key = True

    if not found_key:
        if any(l.strip().lower() == "[general]" for l in lines):
            for i, line in enumerate(lines):
                if line.strip().lower() == "[general]":
                    lines.insert(i + 1, "EnableReplayApi=1\n")
                    break
        else:
            lines.append("\n[General]\nEnableReplayApi=1\n")

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


if __name__ == "__main__":
    path = find_config()
    if not path:
        print("Could not find game.cfg in the usual install locations.")
        print("Install League of Legends first, or add your install's Config")
        print("folder to CANDIDATE_PATHS in this script.")
        sys.exit(1)

    enable_replay_api(path)
    print(f"EnableReplayApi=1 set in {path}")
    print("Launch League, start a replay, then run: python draw_overlay.py")
