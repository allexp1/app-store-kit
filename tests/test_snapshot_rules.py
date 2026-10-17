import hashlib
import json
import pathlib

import pytest

import snapshot_rules as sr


def rules_file(tmp_path, sources):
    path = tmp_path / 'baseline.json'
    path.write_text(json.dumps({'fetched': '2026-01-01', 'sources': sources}))
    return path


@pytest.mark.parametrize('hash_field', [{}, {'text_sha256': None}, {'text_sha256': ''}])
def test_missing_baseline_needs_review(tmp_path, monkeypatch, capsys, hash_field):
    path = rules_file(tmp_path, [{'id': 'a', 'url': 'https://example.test/a', **hash_field}])
    monkeypatch.setattr(sr, 'fetch', lambda url: '<main>same</main>')
    assert sr.check(path) == 3
    assert 'no baseline a' in capsys.readouterr().out


def test_check_same_changed_and_failed(tmp_path, monkeypatch, capsys):
    digest = hashlib.sha256(b'same').hexdigest()
    path = rules_file(tmp_path, [{'id': 'a', 'url': 'a', 'text_sha256': digest}])
    monkeypatch.setattr(sr, 'fetch', lambda url: '<main>same</main>')
    assert sr.check(path) == 0
    monkeypatch.setattr(sr, 'fetch', lambda url: '<main>different</main>')
    assert sr.check(path) == 3
    def fail(url):
        raise OSError('offline')
    monkeypatch.setattr(sr, 'fetch', fail)
    assert sr.check(path) == 3
    assert 'ERROR' in capsys.readouterr().out


def test_freeze_retains_failed_source_dates_and_hashes(tmp_path, monkeypatch, capsys):
    digest = hashlib.sha256(b'same').hexdigest()
    path = rules_file(tmp_path, [
        {'id': 'ok', 'url': 'ok', 'text_sha256': digest},
        {'id': 'failed', 'url': 'failed', 'text_sha256': digest, 'fetched': '2025-12-01'},
        {'id': 'missing', 'url': 'missing', 'text_sha256': None}])
    monkeypatch.setattr(sr, 'DEFAULT_RULES', path)
    def fetch(url):
        if url != 'ok':
            raise OSError('offline')
        return '<main>same</main>'
    monkeypatch.setattr(sr, 'fetch', fetch)
    assert sr.freeze(tmp_path / 'kit') == 3
    frozen = json.loads((tmp_path / 'kit/rules.json').read_text())
    assert frozen['fetched'] == '2026-01-01'
    assert frozen['sources'][0]['fetched'] == sr.dt.date.today().isoformat()
    assert frozen['sources'][1]['fetched'] == '2025-12-01'
    assert frozen['sources'][1]['text_sha256'] == digest
    assert frozen['sources'][2]['fetched'] == '2026-01-01'
    assert frozen['sources'][2]['text_sha256'] is None
    assert 'fetch failed; baseline hashes and fetched dates retained: failed, missing' in capsys.readouterr().out


def test_freeze_success_advances_dates_and_flags_new_baseline(tmp_path, monkeypatch):
    path = rules_file(tmp_path, [{'id': 'a', 'url': 'a'}])
    monkeypatch.setattr(sr, 'DEFAULT_RULES', path)
    monkeypatch.setattr(sr, 'fetch', lambda url: '<main>same</main>')
    assert sr.freeze(tmp_path / 'kit') == 3
    frozen = json.loads((tmp_path / 'kit/rules.json').read_text())
    assert frozen['fetched'] == frozen['sources'][0]['fetched'] == sr.dt.date.today().isoformat()
    monkeypatch.setattr(sr, 'DEFAULT_RULES', tmp_path / 'kit/rules.json')
    assert sr.freeze(tmp_path / 'second-kit') == 0


def test_missing_baseline_is_reported_even_offline(tmp_path, monkeypatch, capsys):
    path = rules_file(tmp_path, [{'id': 'a', 'url': 'a'}])
    def fail(url):
        raise OSError('offline')
    monkeypatch.setattr(sr, 'fetch', fail)
    assert sr.check(path) == 3
    assert 'no baseline a' in capsys.readouterr().out


def test_shipped_rules_track_the_october_2026_guidelines_and_review_help():
    rules = json.loads((pathlib.Path(sr.__file__).parent / 'rules.json').read_text())
    by_id = {s['id']: s for s in rules['sources']}
    assert rules['fetched'] >= '2026-10-17'
    assert by_id['review-guidelines']['text_sha256'].startswith('13bea4397e4204cb')
    assert 'asset-best-practices' in by_id
    help_pages = [s['url'] for s in rules['sources'] if '/help/app-review/' in s['url']]
    assert len(help_pages) >= 5 and all(len(s['text_sha256']) == 64 for s in rules['sources'])
