#!/usr/bin/env python3
"""Check an App Store app preview video with ffprobe against the frozen rules (rules.json "previews").

Usage: preview_check.py [--rules R] [--slot iphone|ipad|ipad-12.9|mac|appletv|vision|...] FILE ...

Errors: container/extension, codec (H.264 or ProRes 422 HQ), length 15-30 s, frame rate <= 30,
resolution for the slot, size <= 500 MB, H.264 level <= 4.0 and progressive, audio stereo 44.1/48 kHz.
Warnings: video bit rate outside the 10-12 Mbps H.264 target, AAC not ~256 kbps, no audio track.
Exit 0 when every file has no errors.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
from fractions import Fraction

HERE = pathlib.Path(__file__).resolve().parent


def ffprobe(path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def _rate(s):
    try:
        f = Fraction(s)
        return float(f) if f else None
    except (ValueError, ZeroDivisionError, TypeError):
        return None


def check(probe: dict, path, slot: str | None, rules: dict):
    """Return (errors, warnings) for one ffprobe result. Pure function, so tests can feed synthetic probes."""
    pr = rules["previews"]
    errs, warns = [], []
    path = pathlib.Path(path)
    ext = path.suffix.lower()
    streams = probe.get("streams", [])
    fmt = probe.get("format", {})
    video = [s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    if len(video) != 1:
        errs.append(f"{len(video)} video streams; need exactly 1")
        return errs, warns
    v = video[0]
    codec = (v.get("codec_name") or "").lower()
    if codec == "h264":
        spec = pr["h264"]
        if ext not in spec["extensions"]:
            errs.append(f"H.264 must be {'/'.join(spec['extensions'])}, got {ext}")
        prof = (v.get("profile") or "").lower()
        if prof and prof not in spec["profiles"]:
            errs.append(f"H.264 profile '{v.get('profile')}' (up to High allowed)")
        lvl = v.get("level")
        if isinstance(lvl, int) and lvl > spec["max_level"]:
            errs.append(f"H.264 level {lvl / 10:.1f} > {spec['max_level'] / 10:.1f}")
        fo = (v.get("field_order") or "progressive").lower()
        if fo not in ("progressive", "unknown"):
            errs.append(f"interlaced video ({fo}); must be progressive")
        br = v.get("bit_rate") or fmt.get("bit_rate")
        if br:
            mbps = int(br) / 1e6
            lo, hi = spec["target_mbps"]
            if not (lo <= mbps <= hi):
                warns.append(f"video bit rate {mbps:.1f} Mbps; Apple's target is {lo}-{hi} Mbps")
    elif codec == "prores":
        spec = pr["prores"]
        if ext not in spec["extensions"]:
            errs.append(f"ProRes must be .mov, got {ext}")
        prof = (v.get("profile") or "")
        if "hq" not in prof.lower():
            errs.append(f"ProRes profile '{prof}'; only ProRes 422 HQ is accepted")
    else:
        errs.append(f"video codec '{codec}'; need H.264 or ProRes 422 HQ")

    dur = float(fmt.get("duration") or v.get("duration") or 0)
    if not (pr["min_seconds"] <= dur <= pr["max_seconds"]):
        errs.append(f"length {dur:.2f} s; must be {pr['min_seconds']}-{pr['max_seconds']} s")

    fps = _rate(v.get("avg_frame_rate")) or _rate(v.get("r_frame_rate"))
    if fps is None:
        warns.append("frame rate unknown")
    elif fps > pr["max_fps"] + 0.01:
        errs.append(f"frame rate {fps:.2f} fps > {pr['max_fps']}")

    w, h = v.get("width"), v.get("height")
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = abs(int(sd["rotation"])) % 180
    if rot == 90:
        w, h = h, w
    if slot:
        res = pr["resolutions"].get(slot)
        if res is None:
            errs.append(f"unknown preview slot '{slot}'; known: {', '.join(pr['resolutions'])}")
        else:
            ok = {tuple(r) for r in res} | {(b, a) for a, b in res}
            if (w, h) not in ok:
                errs.append(f"resolution {w}x{h}; {slot} accepts " + ", ".join(f"{a}x{b}" for a, b in sorted(ok)))
    else:
        warns.append(f"no --slot given; resolution {w}x{h} not checked")

    size = int(fmt.get("size") or (path.stat().st_size if path.exists() else 0))
    if size > pr["max_bytes"]:
        errs.append(f"file is {size / 1e6:.0f} MB > {pr['max_bytes'] / 1e6:.0f} MB")

    ar = pr["audio"]
    if not audio:
        warns.append("no audio track; Apple's spec describes stereo audio, add a silent stereo track to be safe")
    else:
        chans = sum(int(a.get("channels") or 0) for a in audio)
        if chans != ar["channels"]:
            errs.append(f"audio has {chans} channel(s) in {len(audio)} track(s); need stereo (1x2ch or 2x1ch)")
        for a in audio:
            ac = (a.get("codec_name") or "").lower()
            if ac != "aac" and not ac.startswith("pcm"):
                errs.append(f"audio codec '{ac}'; need AAC (or PCM with ProRes)")
            if ac.startswith("pcm") and codec == "h264":
                errs.append("PCM audio is only accepted with ProRes; use AAC with H.264")
            sr = int(a.get("sample_rate") or 0)
            if sr not in ar["sample_rates"]:
                errs.append(f"audio sample rate {sr} Hz; need 44100 or 48000")
            if ac == "aac" and a.get("bit_rate"):
                kbps = int(a["bit_rate"]) / 1000
                if abs(kbps - ar["aac_kbps"]) > 32:
                    warns.append(f"AAC at {kbps:.0f} kbps; Apple specifies {ar['aac_kbps']} kbps")
    return errs, warns


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--slot")
    ap.add_argument("--rules", default=str(HERE / "rules.json"))
    a = ap.parse_args(argv)
    rules = json.loads(pathlib.Path(a.rules).read_text())
    bad = 0
    for f in a.files:
        try:
            errs, warns = check(ffprobe(f), f, a.slot, rules)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            errs, warns = [f"ffprobe failed: {e}"], []
        print(("PASS " if not errs else "FAIL ") + f
              + "".join(f"\n    error: {e}" for e in errs) + "".join(f"\n    warn:  {w}" for w in warns))
        bad += bool(errs)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
