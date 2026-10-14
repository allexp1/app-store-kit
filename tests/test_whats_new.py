import subprocess

import pytest
import yaml

import whats_new as wn


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@example.com", "HOME": str(repo), "PATH": "/usr/bin:/bin"})


def commit(repo, msg):
    git(repo, "commit", "--allow-empty", "-q", "-m", msg)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q")
    commit(r, "feat: first release")
    git(r, "tag", "v1.0.0")
    for msg in ["feat(search): find photos by place", "fix: crash when trash is empty", "docs: update README",
                "test: add deck tests", "chore: bump deps", "WIP trying things", "perf: faster duplicate scan",
                "Add album suggestions", "ci: cache builds", "refactor(kit): split store"]:
        commit(r, msg)
    return r


def test_since_last_tag_groups_and_filters(repo, capsys):
    assert wn.main([str(repo)]) == 0
    out = capsys.readouterr().out
    assert "tag v1.0.0" in out
    assert "New:" in out and "Find photos by place  [search]" in out and "Add album suggestions" in out
    assert "Fixes:" in out and "Crash when trash is empty" in out
    assert "Improvements:" in out and "Faster duplicate scan" in out
    for gone in ["README", "deck tests", "bump deps", "WIP", "cache builds", "split store", "first release"]:
        assert gone not in out
    assert "RAW draft" in out and "4,000" in out


def test_since_recorded_commit_and_record(repo, tmp_path, capsys):
    git(repo, "tag", "-d", "v1.0.0")
    kit = tmp_path / "kit"
    kit.mkdir()
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD~3"], capture_output=True, text=True).stdout.strip()
    assert wn.main(["--record", str(kit), "--version", "1.0.0", "--commit", head, "--date", "2026-10-01"]) == 0
    assert wn.main([str(repo), "--kit", str(kit)]) == 0
    out = capsys.readouterr().out
    assert "release-history.yaml" in out
    assert "Add album suggestions" in out and "Find photos by place" not in out

    (kit / "release-history.yaml").write_text("# keep this comment\n" + (kit / "release-history.yaml").read_text())
    assert wn.main([str(repo), "--record", str(kit), "--version", "1.1.0", "--date", "2026-10-14"]) == 0
    text = (kit / "release-history.yaml").read_text()
    data = yaml.safe_load(text)
    assert "# keep this comment" in text
    assert [r["version"] for r in data["releases"]] == ["1.0.0", "1.1.0"]
    assert data["last_release_commit"] == data["releases"][-1]["commit"] != head


def test_explicit_since_and_no_anchor(repo, capsys):
    git(repo, "tag", "-d", "v1.0.0")
    assert wn.main([str(repo)]) == 0
    assert "whole history" in capsys.readouterr().out
    assert wn.main([str(repo), "--since", "HEAD~1"]) == 0
    out = capsys.readouterr().out
    assert "1 of 1 commits" in out or "0 of 1 commits" in out


def test_classify():
    assert wn.classify("Merge branch 'x'")[0] is None
    assert wn.classify("style: format")[0] is None
    assert wn.classify("feat!: new deck")[0] == "feat"
    assert wn.classify("Fix the badge")[0] == "fix"
    assert wn.classify("Tweak colours")[0] == "other"
