"""Offline TestFlight contracts and workflow tests; no API key or network access."""
import copy
import json
import urllib.parse

import pytest
import yaml

import testflight as tf
from asc_api import Client


class FakeTestFlight:
    """Small strict v1 transport, including pagination and relationship read-backs."""
    CREATE = {
        "betaGroups": ({"name", "isInternalGroup", "hasAccessToAllBuilds", "publicLinkEnabled",
                        "publicLinkLimitEnabled", "publicLinkLimit"}, {"app"}),
        "betaTesters": ({"email"}, {"betaGroups"}),
        "betaAppLocalizations": ({"locale", "description", "feedbackEmail", "marketingUrl", "privacyPolicyUrl"}, {"app"}),
        "betaBuildLocalizations": ({"locale", "whatsNew"}, {"build"}),
        "betaAppReviewSubmissions": (set(), {"build"}),
    }
    PATCH = {
        "betaGroups": {"name", "publicLinkEnabled", "publicLinkLimitEnabled", "publicLinkLimit"},
        "betaAppLocalizations": {"description", "feedbackEmail", "marketingUrl", "privacyPolicyUrl"},
        "betaBuildLocalizations": {"whatsNew"},
        "betaAppReviewDetails": set(tf.CONTACT_FIELDS.values()) | {"notes", "demoAccountRequired"},
    }

    def __init__(self):
        self.rows, self.calls, self.fail, self.n = {}, [], {}, 0
        self.ignore_patch = False
        self.add("apps", "app", {"bundleId": "com.example.beta"})
        self.add("preReleaseVersions", "version", {"version": "1.2", "platform": "IOS"})
        self.add("builds", "build", {"version": "42", "processingState": "VALID", "expired": False,
                 "buildAudienceType": "APP_STORE_ELIGIBLE"}, {"app": tf.linkage("apps", "app"),
                 "preReleaseVersion": tf.linkage("preReleaseVersions", "version")})
        self.add("buildBetaDetails", "detail", {"externalBuildState": "READY_FOR_BETA_SUBMISSION"},
                 {"build": tf.linkage("builds", "build")})
        self.add("betaAppReviewDetails", "review", {}, {"app": tf.linkage("apps", "app")})

    def add(self, kind, rid, attributes=None, relationships=None):
        row = tf.body(kind, attributes or {}, relationships or {}, rid)["data"]
        self.rows[rid] = row
        return row

    def related(self, rid, rel):
        row = self.rows[rid]
        forward = row.get("relationships", {}).get(rel, {}).get("data")
        if forward is not None:
            return forward
        inverse = {"betaAppLocalizations": ("betaAppLocalizations", "app"),
                   "betaAppReviewDetail": ("betaAppReviewDetails", "app"),
                   "betaGroups": ("betaGroups", "app"),
                   "betaBuildLocalizations": ("betaBuildLocalizations", "build"),
                   "buildBetaDetail": ("buildBetaDetails", "build"),
                   "betaAppReviewSubmission": ("betaAppReviewSubmissions", "build"),
                   "betaFeedbackCrashSubmissions": ("betaFeedbackCrashSubmissions", "app"),
                   "betaFeedbackScreenshotSubmissions": ("betaFeedbackScreenshotSubmissions", "app")}
        if rel == "betaTesters":
            return [tf.linkage(r["type"], r["id"]) for r in self.rows.values() if r["type"] == "betaTesters"
                    and tf.linkage("betaGroups", rid) in r.get("relationships", {}).get("betaGroups", {}).get("data", [])]
        if rel == "builds":
            return []
        kind, inverse_rel = inverse[rel]
        found = [tf.linkage(r["type"], r["id"]) for r in self.rows.values() if r["type"] == kind and
                 r.get("relationships", {}).get(inverse_rel, {}).get("data", {}).get("id") == rid]
        return (found[0] if found else None) if rel in {"betaAppReviewDetail", "buildBetaDetail", "betaAppReviewSubmission"} else found

    def transport(self, method, url, headers, raw, timeout=120):
        u = urllib.parse.urlparse(url)
        path = u.path
        params = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        payload = json.loads(raw) if raw else None
        self.calls.append((method, path, params, copy.deepcopy(payload)))
        assert path.startswith("/v1/"), path
        if (method, path) in self.fail:
            return self.fail[method, path], {}, json.dumps({"errors": [{"detail": "private remote address: hidden@example.net"}]}).encode()
        parts = path.split("/")[2:]
        kind = parts[0]
        if method == "GET":
            if len(parts) == 1:
                result = [r for r in self.rows.values() if r["type"] == kind]
                for key, value in params.items():
                    if key in {"filter[bundleId]", "filter[email]", "filter[version]"}:
                        field = key[7:-1]
                        result = [r for r in result if str(tf.attrs(r).get(field)) == value]
                    elif key == "filter[app]":
                        result = [r for r in result if r["relationships"]["app"]["data"]["id"] == value]
                    elif key.startswith("filter[preReleaseVersion."):
                        field = key.split(".")[1][:-1]
                        result = [r for r in result if tf.attrs(self.rows[r["relationships"]["preReleaseVersion"]["data"]["id"]])[field] == value]
                    else:
                        assert key in {"limit", "sort", "cursor"}, key
            elif len(parts) == 2:
                result = self.rows.get(parts[1])
            else:
                rel = parts[-1]
                result = self.related(parts[1], rel)
                if len(parts) == 3 and result is not None:
                    result = [self.rows[r["id"]] for r in result] if isinstance(result, list) else self.rows[result["id"]]
                if not isinstance(result, list):
                    assert not params, "to-one relationship does not accept limit"
            if result is None:
                return 404, {}, b'{"errors": []}'
            doc = {"data": result}
            # Two items per page forces use of Client.get_all everywhere.
            if isinstance(result, list):
                start = int(params.get("cursor", "0"))
                doc["data"] = result[start:start + 2]
                if start + 2 < len(result):
                    doc["links"] = {"next": path + "?" + urllib.parse.urlencode({**params, "cursor": start + 2})}
            return 200, {}, json.dumps(doc).encode()
        assert method in {"POST", "PATCH"}, "No DELETE is allowed"
        data = payload["data"]
        if len(parts) == 4:
            assert method == "POST" and kind == "betaGroups" and parts[2] == "relationships"
            assert parts[3] in {"builds", "betaTesters"}
            assert all(r["type"] == parts[3] and r["id"] in self.rows for r in data)
            current = self.related(parts[1], parts[3])
            self.rows[parts[1]].setdefault("relationships", {})[parts[3]] = {"data": current + data}
            return 204, {}, b""
        assert data["type"] == kind
        if method == "POST":
            assert len(parts) == 1 and kind in self.CREATE
            allowed, rels = self.CREATE[kind]
            assert set(data.get("attributes", {})) <= allowed
            assert set(data.get("relationships", {})) == rels
            self.n += 1
            rid = f"new{self.n}"
            resource = copy.deepcopy(data)
            resource["id"] = rid
            if kind == "betaAppReviewSubmissions":
                resource["attributes"] = {"betaReviewState": "WAITING_FOR_REVIEW"}
            self.rows[rid] = resource
        else:
            assert len(parts) == 2 and data["id"] == parts[1]
            assert set(data.get("attributes", {})) <= self.PATCH[kind]
            resource = self.rows[parts[1]]
            if not self.ignore_patch:
                resource["attributes"].update(data.get("attributes", {}))
        return 200, {}, json.dumps({"data": resource}).encode()

    @property
    def writes(self):
        return [c for c in self.calls if c[0] != "GET"]


@pytest.fixture
def setup(tmp_path):
    def put(name, value):
        (tmp_path / name).write_text(yaml.safe_dump(value, sort_keys=False))
    put("facts.yaml", {"app": {"bundle_id": "com.example.beta", "version": "1.2", "build": "42"}})
    put("testflight.yaml", {"groups": [
        {"name": "Team", "type": "internal"},
        {"name": "Preview", "type": "external", "public_link": {"enabled": True, "limit": 250},
         "testers_private": "testflight.external_testers"}],
        "test_information": {"en-US": {"description": "A beta app", "feedback_email": "feedback@example.com",
                                        "what_to_test": "Onboarding and restore"}},
        "beta_review": {"contact_private": "testflight.review_contact", "demo_account_required": False}})
    put("private.yaml", {"testflight": {"external_testers": ["tester@example.com"], "review_contact": {
        "first_name": "Tester First", "last_name": "Tester Last", "phone": "+1 555 123 4567",
        "email": "review@example.com", "demo_password": 'p\\a"ss<&\né'}}})
    fake = FakeTestFlight()
    client = Client(transport=fake.transport, max_retries=0)
    return tmp_path, fake, client


def run(setup, *args):
    path, _, client = setup
    return tf.main([args[0], str(path), *args[1:]], client=client)


def change(path, name, fn):
    value = yaml.safe_load((path / name).read_text())
    fn(value)
    (path / name).write_text(yaml.safe_dump(value))


@pytest.mark.parametrize("command", ["apply", "submit-beta"])
@pytest.mark.parametrize("dry", [False, True])
def test_yes_gate_precedes_kit_and_auth(tmp_path, monkeypatch, command, dry):
    monkeypatch.setattr(tf, "make_client", lambda *a, **k: pytest.fail("auth must not run"))
    assert tf.main([command, str(tmp_path / "missing"), *(["--dry-run"] if dry else [])]) == 2


def test_plan_get_only_and_masks_private(setup, capsys):
    path, fake, _ = setup
    assert run(setup, "plan") == 0
    assert not fake.writes
    saved = json.loads((path / "testflight-plan.json").read_text())
    assert any(x["body"]["data"].get("attributes", {}).get("publicLinkLimit") == 250
               for x in saved["operations"] if isinstance(x["body"]["data"], dict))
    text = (path / "testflight-plan.md").read_text() + json.dumps(saved) + capsys.readouterr().out
    for value in tf.cg.private_values(yaml.safe_load((path / "private.yaml").read_text())):
        assert value not in text
    assert "@example.com" not in text


def test_apply_verified_and_idempotent(setup):
    path, fake, _ = setup
    (path / "connect-progress.yaml").write_text("steps:\n  unrelated:\n    status: todo\n")
    assert run(setup, "plan") == 0
    assert run(setup, "apply", "--yes") == 0
    count = len(fake.writes)
    assert count >= 7
    assert run(setup, "apply", "--yes") == 0
    assert len(fake.writes) == count
    progress = yaml.safe_load((path / "connect-progress.yaml").read_text())
    assert progress["steps"]["unrelated"]["status"] == "todo"
    assert progress["steps"]["testflight/distribution"]["live"]["Verified requests"] == count
    for i, call in enumerate(fake.calls):
        if call[0] != "GET":
            assert fake.calls[i + 1][0] == "GET"
    assert "tester@example.com" not in (path / "connect-progress.yaml").read_text()


def test_dry_run_prints_without_writes_or_progress(setup, capsys):
    path, fake, _ = setup
    assert run(setup, "plan") == 0
    before = (path / "testflight-plan.json").read_bytes()
    assert run(setup, "apply", "--yes", "--dry-run") == 0
    assert not fake.writes
    assert not (path / "connect-progress.yaml").exists()
    assert (path / "testflight-plan.json").read_bytes() == before
    output = capsys.readouterr().out
    assert "would send: POST /v1/betaTesters" in output
    assert "tester@example.com" not in output
    assert 'p\\a"ss' not in output


@pytest.mark.parametrize("filename", ["facts.yaml", "testflight.yaml", "private.yaml"])
def test_stale_inputs_refused(setup, filename):
    path, fake, _ = setup
    assert run(setup, "plan") == 0
    with (path / filename).open("a") as handle:
        handle.write("\n# changed\n")
    assert run(setup, "apply", "--yes") == 2
    assert not fake.writes


def test_live_drift_refused(setup):
    _, fake, _ = setup
    assert run(setup, "plan") == 0
    fake.add("betaGroups", "existing", {"name": "Preview", "isInternalGroup": False}, {"app": tf.linkage("apps", "app")})
    assert run(setup, "apply", "--yes") == 2
    assert not fake.writes


def test_partial_failure_requires_replan_without_duplicate_creates(setup):
    _, fake, _ = setup
    assert run(setup, "plan") == 0
    fake.fail["POST", "/v1/betaGroups"] = 500
    assert run(setup, "apply", "--yes") == 1
    creates = [c for c in fake.writes if c[1] == "/v1/betaAppLocalizations"]
    assert len(creates) == 1
    fake.fail.clear()
    assert run(setup, "apply", "--yes") == 2
    assert run(setup, "plan") == 0
    assert run(setup, "apply", "--yes") == 0
    assert len([c for c in fake.writes if c[1] == "/v1/betaAppLocalizations"]) == 1


def test_failed_readback_does_not_mark_done(setup):
    path, fake, _ = setup
    fake.ignore_patch = True
    assert run(setup, "plan") == 0
    assert run(setup, "apply", "--yes") == 2
    assert not (path / "connect-progress.yaml").exists()


@pytest.mark.parametrize("mutation", [
    lambda c: c["groups"][1].update(testers=["leak@example.com"]),
    lambda c: c["groups"][1]["public_link"].update(limit=10001),
    lambda c: c["groups"][1]["public_link"].update(enabled="false"),
    lambda c: c["groups"][0].update(public_link={"enabled": True}),
    lambda c: c["groups"][1].update(name="Team"),
    lambda c: c["groups"][1].update(type="other"),
    lambda c: c["beta_review"].update(email="leak@example.com"),
    lambda c: c.update(groups=[c["groups"][1]]),
])
def test_invalid_config_rejected_before_api(setup, mutation):
    path, fake, _ = setup
    change(path, "testflight.yaml", mutation)
    assert run(setup, "plan") == 2
    assert not fake.writes


def test_new_internal_tester_requires_browser(setup, capsys):
    path, fake, _ = setup
    change(path, "testflight.yaml", lambda c: c["groups"][0].update(testers_private="testflight.external_testers"))
    assert run(setup, "plan") == 2
    assert "Add new internal testers" in capsys.readouterr().out
    assert not fake.writes


@pytest.mark.parametrize("attributes", [{"processingState": "PROCESSING"}, {"expired": True},
                                      {"expirationDate": "2020-01-01T00:00:00Z"},
                                      {"buildAudienceType": "INTERNAL_ONLY"}])
def test_ineligible_build_refused(setup, attributes):
    _, fake, _ = setup
    fake.rows["build"]["attributes"].update(attributes)
    assert run(setup, "plan") == 2
    assert not fake.writes


def test_duplicate_build_number_not_arbitrary(setup):
    _, fake, _ = setup
    fake.add("builds", "duplicate", tf.attrs(fake.rows["build"]),
             {"app": tf.linkage("apps", "app"), "preReleaseVersion": tf.linkage("preReleaseVersions", "version")})
    assert run(setup, "plan") == 2


def test_app_id_bundle_mismatch(setup):
    path, _, _ = setup
    (path / "connect.yaml").write_text("api: {app_id: app}\n")
    change(path, "facts.yaml", lambda c: c["app"].update(bundle_id="com.other.app"))
    assert run(setup, "status") == 2


def prepare_beta(setup):
    assert run(setup, "plan") == 0
    assert run(setup, "apply", "--yes") == 0
    setup[1].calls.clear()


def test_beta_review_separate_plan_exact_target_and_readback(setup):
    path, fake, _ = setup
    prepare_beta(setup)
    assert run(setup, "submit-beta", "--build", "42", "--yes") == 2
    assert run(setup, "plan", "--build", "42", "--submit-beta") == 0
    assert not fake.writes
    assert (path / "testflight-beta-plan.md").exists()
    assert run(setup, "submit-beta", "--build", "42", "--yes", "--dry-run") == 0
    assert not fake.writes
    assert run(setup, "submit-beta", "--build", "43", "--yes") == 2
    assert run(setup, "submit-beta", "--build", "42", "--yes") == 0
    assert len(fake.writes) == 1
    assert fake.writes[0][1] == "/v1/betaAppReviewSubmissions"
    assert fake.writes[0][3]["data"]["relationships"]["build"]["data"]["id"] == "build"
    assert run(setup, "submit-beta", "--build", "42", "--yes") == 0
    assert len(fake.writes) == 1


def test_another_build_in_review_blocks_submission(setup):
    _, fake, _ = setup
    prepare_beta(setup)
    fake.add("builds", "other", {**tf.attrs(fake.rows["build"]), "version": "41"},
             {"app": tf.linkage("apps", "app"), "preReleaseVersion": tf.linkage("preReleaseVersions", "version")})
    fake.add("betaAppReviewSubmissions", "pending", {"betaReviewState": "IN_REVIEW"}, {"build": tf.linkage("builds", "other")})
    assert run(setup, "plan", "--build", "42", "--submit-beta") == 2
    assert not fake.writes


@pytest.mark.parametrize("state", ["BETA_APPROVED", "IN_BETA_TESTING", "READY_FOR_BETA_TESTING"])
def test_approved_build_no_resubmission(setup, state):
    _, fake, _ = setup
    fake.rows["detail"]["attributes"]["externalBuildState"] = state
    assert run(setup, "plan", "--build", "42", "--submit-beta") == 0
    assert run(setup, "submit-beta", "--build", "42", "--yes") == 0
    assert not fake.writes


def test_missing_review_metadata_blocks_submission(setup):
    assert run(setup, "plan", "--build", "42", "--submit-beta") == 2
    assert not setup[1].writes


def seed_feedback(fake, kind, rid, comment, date="2026-10-01T00:00:00Z"):
    row = fake.add(kind, rid, {"comment": comment, "email": "remote@example.com", "createdDate": date},
                   {"app": tf.linkage("apps", "app"), "build": tf.linkage("builds", "build")})
    if kind == "betaFeedbackCrashSubmissions":
        fake.add("betaCrashLogs", "log" + rid, {"logText": "Exception Type: EXC_BAD_ACCESS (SIGSEGV)\n/private/secret/path remote@example.com"})
        row["relationships"]["crashLog"] = {"data": tf.linkage("betaCrashLogs", "log" + rid)}


def test_feedback_paging_since_grouping_and_crash_summary(setup, capsys):
    path, fake, _ = setup
    seed_feedback(fake, "betaFeedbackScreenshotSubmissions", "old", "lost data", "2026-09-30T23:59:59Z")
    seed_feedback(fake, "betaFeedbackScreenshotSubmissions", "loss", "lost data remote@example.com")
    seed_feedback(fake, "betaFeedbackScreenshotSubmissions", "access", "VoiceOver focus wrong")
    seed_feedback(fake, "betaFeedbackScreenshotSubmissions", "purchase", "restore purchase fails")
    seed_feedback(fake, "betaFeedbackCrashSubmissions", "crash", "crash")
    assert run(setup, "feedback", "--since", "2026-10-01") == 0
    text = (path / "TESTFLIGHT-FEEDBACK.md").read_text()
    assert "Feedback old" not in text
    assert "Build 42 (ID build) — Accessibility" in text
    assert "EXC_BAD_ACCESS, SIGSEGV" in text
    assert "Release blockers" in text and "feedback purchase" in text
    assert "remote@example.com" not in text + capsys.readouterr().out
    assert "/private/secret" not in text and "focus wrong" not in text
    assert any(c[2].get("cursor") == "2" for c in fake.calls)
    assert not fake.writes


@pytest.mark.parametrize("code", [403, 404, 405, 501])
def test_feedback_unavailable_is_visible_gap(setup, code):
    path, fake, _ = setup
    fake.fail["GET", "/v1/apps/app/betaFeedbackScreenshotSubmissions"] = code
    assert run(setup, "feedback") == 1
    report = (path / "TESTFLIGHT-FEEDBACK.md").read_text()
    assert "Coverage gaps" in report and f"HTTP {code}" in report


@pytest.mark.parametrize("code", [401, 429, 500])
def test_feedback_auth_and_server_errors_not_swallowed(setup, code, capsys):
    path, fake, _ = setup
    fake.fail["GET", "/v1/apps/app/betaFeedbackScreenshotSubmissions"] = code
    assert run(setup, "feedback") == 1
    assert not (path / "TESTFLIGHT-FEEDBACK.md").exists()
    assert "hidden@example.net" not in capsys.readouterr().out


def test_missing_feedback_timestamp_not_silently_dropped(setup):
    path, fake, _ = setup
    seed_feedback(fake, "betaFeedbackScreenshotSubmissions", "badtime", "lost data", None)
    assert run(setup, "feedback", "--since", "2026-10-01") == 1
    assert "badtime" in (path / "TESTFLIGHT-FEEDBACK.md").read_text()


def test_bad_date_fails_before_api(setup):
    _, fake, _ = setup
    assert run(setup, "feedback", "--since", "yesterday") == 2
    assert not fake.calls


def test_status_counts_all_pages_without_emails(setup, capsys):
    _, fake, _ = setup
    fake.add("betaGroups", "team", {"name": "Team", "isInternalGroup": True}, {"app": tf.linkage("apps", "app")})
    for i in range(5):
        fake.add("betaTesters", f"tester{i}", {"email": f"person{i}@example.com"},
                 {"betaGroups": [tf.linkage("betaGroups", "team")]})
    assert run(setup, "status") == 0
    output = capsys.readouterr().out
    assert "testers=5" in output and "processing=VALID" in output
    assert "@example.com" not in output
    assert not fake.writes


def test_private_mask_handles_short_and_escaped_values(setup):
    path, _, _ = setup
    change(path, "private.yaml", lambda c: c["testflight"]["review_contact"].update(demo_password="x"))
    kit = tf.Kit(path)
    safe = kit.safe({"value": "x", "text": 'x "<x>" 6x', "email": "person@example.com"})
    # A whole value that is the short secret is masked; inside free text a 1-character value isn't scrubbed
    # (it would corrupt every word and number), and the JSON stays valid.
    assert safe["value"] == "[private]" and safe["text"] == 'x "<x>" 6x'
    assert "@" not in json.dumps(safe)


def test_malformed_private_yaml_never_echoes_parser_excerpt(setup, capsys):
    path, _, _ = setup
    (path / "private.yaml").write_text('secret: ["very-private-password"\n')
    assert run(setup, "plan") == 2
    assert "very-private-password" not in capsys.readouterr().out


def test_template_is_valid_with_private_structure(tmp_path):
    template = tf.pathlib.Path(tf.__file__).resolve().parent.parent / "templates/testflight.example.yaml"
    (tmp_path / "testflight.yaml").write_text(template.read_text())
    (tmp_path / "private.yaml").write_text("testflight:\n  external_testers: []\n  review_contact: {}\n")
    tf.Kit(tmp_path).validate()


def test_existing_text_can_be_cleared_and_public_link_disabled(setup):
    path, fake, _ = setup
    prepare_beta(setup)
    change(path, "testflight.yaml", lambda c: c["test_information"]["en-US"].update(description="", what_to_test=""))
    change(path, "testflight.yaml", lambda c: c["groups"][1].update(public_link={"enabled": False, "limit": None}))
    assert run(setup, "plan") == 0
    assert run(setup, "apply", "--yes") == 0
    assert all(c[0] == "PATCH" for c in fake.writes)
    patches = {c[3]["data"]["type"]: c[3]["data"]["attributes"] for c in fake.writes}
    assert patches["betaBuildLocalizations"] == {"whatsNew": ""}
    assert patches["betaAppLocalizations"] == {"description": ""}
    assert patches["betaGroups"] == {"publicLinkEnabled": False, "publicLinkLimitEnabled": False}


def test_same_new_tester_in_two_groups_created_once(setup):
    path, fake, _ = setup
    change(path, "testflight.yaml", lambda c: c["groups"].append({"name": "Second", "type": "external",
                                                               "testers_private": "testflight.external_testers"}))
    assert run(setup, "plan") == 0
    assert run(setup, "apply", "--yes") == 0
    assert len([c for c in fake.writes if c[1] == "/v1/betaTesters"]) == 1
    relation = next(c for c in fake.writes if c[1].endswith("/relationships/betaTesters"))
    assert relation[3]["data"][0]["id"] in fake.rows


def test_existing_internal_tester_can_join_additional_group(setup):
    path, fake, _ = setup
    fake.add("betaGroups", "staff", {"name": "Staff", "isInternalGroup": True}, {"app": tf.linkage("apps", "app")})
    fake.add("betaTesters", "person", {"email": "tester@example.com"},
             {"betaGroups": [tf.linkage("betaGroups", "staff")]})
    change(path, "testflight.yaml", lambda c: c["groups"][0].update(testers_private="testflight.external_testers"))
    assert run(setup, "plan") == 0
    assert run(setup, "apply", "--yes") == 0
    assert not [c for c in fake.writes if c[1] == "/v1/betaTesters"]
    assert len([c for c in fake.writes if c[1].endswith("/relationships/betaTesters")]) == 2


def test_external_tester_limit_prevents_writes(setup):
    path, fake, _ = setup
    change(path, "private.yaml", lambda c: c["testflight"].update(
        external_testers=[f"tester{i}@example.com" for i in range(10001)]))
    assert run(setup, "plan") == 2
    assert not fake.writes


def test_crash_log_unavailable_keeps_crash_as_blocker(setup):
    path, fake, _ = setup
    seed_feedback(fake, "betaFeedbackCrashSubmissions", "crash", "crash")
    fake.fail["GET", "/v1/betaFeedbackCrashSubmissions/crash/crashLog"] = 404
    assert run(setup, "feedback") == 1
    report = (path / "TESTFLIGHT-FEEDBACK.md").read_text()
    assert "Crashes, feedback crash" in report and "crash log unavailable" in report


def test_missing_and_invalid_plan_fail_without_writes(setup):
    path, fake, _ = setup
    assert run(setup, "apply", "--yes") == 2
    (path / "testflight-plan.json").write_text("[]")
    assert run(setup, "apply", "--yes") == 2
    assert not fake.writes


def test_symbolic_reference_like_copy_is_sent_unchanged(setup):
    path, fake, _ = setup
    change(path, "testflight.yaml", lambda c: c["test_information"]["en-US"].update(what_to_test="Enter @group0 in search"))
    assert run(setup, "plan") == 0
    assert run(setup, "apply", "--yes") == 0
    request = next(c for c in fake.writes if c[1] == "/v1/betaBuildLocalizations")
    assert request[3]["data"]["attributes"]["whatsNew"] == "Enter @group0 in search"


@pytest.mark.parametrize("password", ["a", "id", "42"])
def test_short_private_value_does_not_corrupt_plan_schema(setup, password):
    path, fake, _ = setup
    change(path, "private.yaml", lambda c: c["testflight"]["review_contact"].update(demo_password=password))
    assert run(setup, "plan") == 0
    saved = json.loads((path / "testflight-plan.json").read_text())
    review = next(op for op in saved["operations"] if "demoAccountPassword" in
                  (op["body"]["data"].get("attributes", {}) if isinstance(op["body"]["data"], dict) else {}))
    assert review["body"]["data"]["attributes"]["demoAccountPassword"] == "[private]"
    assert run(setup, "apply", "--yes") == 0
    assert fake.rows["review"]["attributes"]["demoAccountPassword"] == password
