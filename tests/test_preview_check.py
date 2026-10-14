import copy
import pathlib
import shutil
import subprocess

import pytest

import preview_check as pc
import validate_kit as vk

GOOD = {
    "format": {"duration": "20.0", "size": "25000000", "bit_rate": "11000000"},
    "streams": [
        {"codec_type": "video", "codec_name": "h264", "profile": "High", "level": 40, "width": 886, "height": 1920,
         "avg_frame_rate": "30/1", "r_frame_rate": "30/1", "field_order": "progressive", "bit_rate": "11000000"},
        {"codec_type": "audio", "codec_name": "aac", "channels": 2, "sample_rate": "48000", "bit_rate": "256000"},
    ],
}


def probe(**changes):
    p = copy.deepcopy(GOOD)
    for k, v in changes.items():
        where, key = k.split("__")
        target = p["format"] if where == "f" else p["streams"][0 if where == "v" else 1]
        target[key] = v
    return p


def chk(p, name="a.mov", slot="iphone", rules=None):
    return pc.check(p, pathlib.Path(name), slot, rules)


def test_good_preview_passes(rules):
    errs, warns = chk(GOOD, rules=rules)
    assert errs == [] and warns == []


@pytest.mark.parametrize("changes,needle", [
    ({"f__duration": "31.0"}, "length 31.00"),
    ({"f__duration": "14.5"}, "length 14.50"),
    ({"v__avg_frame_rate": "60/1"}, "frame rate 60.00"),
    ({"v__width": 1080}, "resolution 1080x1920"),
    ({"v__codec_name": "hevc"}, "video codec 'hevc'"),
    ({"v__level": 51}, "level 5.1"),
    ({"v__field_order": "tt"}, "interlaced"),
    ({"a__channels": 1}, "stereo"),
    ({"a__sample_rate": "22050"}, "sample rate 22050"),
    ({"a__codec_name": "mp3"}, "audio codec 'mp3'"),
    ({"f__size": "600000000"}, "MB >"),
])
def test_rule_violations(rules, changes, needle):
    errs, _ = chk(probe(**changes), rules=rules)
    assert any(needle in e for e in errs), errs


def test_ipad_resolution_and_landscape(rules):
    assert chk(probe(v__width=1200, v__height=1600), slot="ipad", rules=rules)[0] == []
    assert chk(probe(v__width=1920, v__height=886), rules=rules)[0] == []
    assert chk(GOOD, slot="ipad", rules=rules)[0]


def test_rotation_metadata_is_honoured(rules):
    p = probe(v__width=1920, v__height=886)
    p["streams"][0]["side_data_list"] = [{"rotation": -90}]
    assert chk(p, rules=rules)[0] == []


def test_prores_rules(rules):
    p = probe(v__codec_name="prores", v__profile="LT")
    assert any("422 HQ" in e for e in chk(p, rules=rules)[0])
    p = probe(v__codec_name="prores", v__profile="HQ")
    assert chk(p, rules=rules)[0] == []
    assert any("must be .mov" in e for e in chk(p, name="a.mp4", rules=rules)[0])


def test_soft_warnings(rules):
    _, warns = chk(probe(v__bit_rate="4000000", a__bit_rate="128000"), rules=rules)
    assert any("bit rate 4.0" in w for w in warns) and any("128 kbps" in w for w in warns)
    p = copy.deepcopy(GOOD); p["streams"].pop()
    errs, warns = chk(p, rules=rules)
    assert errs == [] and any("no audio" in w for w in warns)


def test_h264_extension(rules):
    assert any("H.264 must be" in e for e in chk(GOOD, name="a.avi", rules=rules)[0])


@pytest.fixture(scope="module")
def real_video(tmp_path_factory):
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("ffmpeg/ffprobe not installed")
    out = tmp_path_factory.mktemp("vid") / "preview.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=886x1920:rate=30:duration=16",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000", "-t", "16",
        "-c:v", "libx264", "-preset", "ultrafast", "-profile:v", "high", "-level", "4.0", "-pix_fmt", "yuv420p",
        "-b:v", "11M", "-c:a", "aac", "-b:a", "256k", "-shortest", str(out)], check=True)
    return out


def test_real_file_through_ffprobe(real_video, rules):
    errs, _ = pc.check(pc.ffprobe(real_video), real_video, "iphone", rules)
    assert errs == []
    assert pc.main(["--slot", "iphone", str(real_video)]) == 0
    assert pc.main(["--slot", "ipad", str(real_video)]) == 1


def test_validate_kit_runs_preview_checks(real_video, tmp_path):
    from PIL import Image
    shot = tmp_path / "screenshots" / "en-US" / "iphone-di-medium" / "01.png"
    shot.parent.mkdir(parents=True)
    Image.new("RGB", (1206, 2622)).save(shot)
    pdir = tmp_path / "previews" / "en-US" / "iphone-di-medium"
    pdir.mkdir(parents=True)
    shutil.copy(real_video, pdir / "01.mp4")
    assert vk.main([str(tmp_path), "--platforms", "iphone", "--today", "2026-10-14"]) == 0
    pdir2 = tmp_path / "previews" / "en-US" / "ipad-13"
    pdir2.mkdir(parents=True)
    shutil.copy(real_video, pdir2 / "01.mp4")
    assert vk.main([str(tmp_path), "--platforms", "iphone", "--today", "2026-10-14"]) == 1
