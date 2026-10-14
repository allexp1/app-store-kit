#!/usr/bin/env python3
"""Plan TestFlight distribution, submit beta review, and triage feedback (API 4.5.1).

See references/testflight.md. All Apple writes require --yes and a matching saved
plan. Private values are resolved only in memory; no testers or groups are deleted.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import pathlib
import re

import yaml

import connect_guide as cg
from asc_api import ASCError, ConfigError, make_client

EMAIL = re.compile(r"[^\s<>\"'(),;:@]+@[^\s<>\"'(),;:@]+", re.I)
APP_FIELDS = {"description": "description", "feedback_email": "feedbackEmail",
              "marketing_url": "marketingUrl", "privacy_policy_url": "privacyPolicyUrl"}
CONTACT_FIELDS = {"first_name": "contactFirstName", "last_name": "contactLastName",
                  "phone": "contactPhone", "email": "contactEmail",
                  "demo_username": "demoAccountName", "demo_password": "demoAccountPassword"}
READY = {"READY_FOR_BETA_TESTING", "IN_BETA_TESTING", "BETA_APPROVED"}


def attrs(resource):
    return (resource or {}).get("attributes") or {}


def linkage(kind, rid):
    return {"type": kind, "id": rid}


def body(kind, attributes=None, relationships=None, rid=None):
    data = {"type": kind}
    if rid is not None:
        data["id"] = rid
    if attributes is not None:
        data["attributes"] = attributes
    if relationships:
        data["relationships"] = {k: {"data": v} for k, v in relationships.items()}
    return {"data": data}


def read_yaml(path):
    value = yaml.safe_load(path.read_text()) if path.exists() else {}
    if value is not None and not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a mapping.")
    return value or {}


class Kit:
    def __init__(self, path):
        self.path = pathlib.Path(path)
        if not self.path.is_dir():
            raise ValueError("KIT must be an existing directory.")
        self.private = read_yaml(self.path / "private.yaml")
        self.pvals = cg.private_values(self.private)
        self.facts = read_yaml(self.path / "facts.yaml")
        self.connect = read_yaml(self.path / "connect.yaml")
        self.config = read_yaml(self.path / "testflight.yaml")
        self.app = self.facts.get("app") or {}

    def safe(self, value, mask_keys=True):
        # Mask before serialization: quotes, Unicode and newlines remain valid JSON/YAML.
        if isinstance(value, dict):
            return {(self.safe(str(k)) if mask_keys else k): self.safe(v, mask_keys) for k, v in value.items()}
        if isinstance(value, list):
            return [self.safe(v, mask_keys) for v in value]
        if isinstance(value, str):
            return EMAIL.sub("[email]", cg.mask_obj(value, self.pvals))
        return value

    def emit(self, value):
        print(self.safe(value))

    def sources(self):
        result = {}
        for name in ("facts.yaml", "connect.yaml", "testflight.yaml"):
            path = self.path / name
            result[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        # Do not store a password-derived digest in a public plan.
        path = self.path / "private.yaml"
        result["private.yaml"] = [path.stat().st_mtime_ns, path.stat().st_size] if path.exists() else None
        return result

    def validate(self):
        if not (self.path / "testflight.yaml").is_file():
            raise ValueError("Create testflight.yaml from templates/testflight.example.yaml first.")
        config = self.config
        unknown = set(config) - {"build", "groups", "test_information", "beta_review"}
        if unknown:
            raise ValueError("Unknown testflight.yaml fields; see the example template.")
        groups = config.get("groups", [])
        if not isinstance(groups, list):
            raise ValueError("groups must be a list.")
        names = set()
        for group in groups:
            if not isinstance(group, dict) or set(group) - {"name", "type", "public_link", "testers_private"}:
                raise ValueError("Invalid group; tester emails belong only in private.yaml.")
            name = group.get("name")
            if not isinstance(name, str) or not name.strip() or name in names or "@" in name:
                raise ValueError("Group names must be unique, nonempty, and contain no email addresses.")
            names.add(name)
            if group.get("type") not in ("internal", "external"):
                raise ValueError("Group type must be internal or external.")
            public = group.get("public_link", {})
            if not isinstance(public, dict) or set(public) - {"enabled", "limit"}:
                raise ValueError("public_link accepts enabled and limit.")
            if "enabled" in public and not isinstance(public["enabled"], bool):
                raise ValueError("public_link.enabled must be true or false.")
            limit = public.get("limit")
            if limit is not None and (type(limit) is not int or not 1 <= limit <= 10000):
                raise ValueError("Public link limit must be 1–10000, or null to disable the limit.")
            if group["type"] == "internal" and public:
                raise ValueError("Public links are only available for external groups.")
            self.testers(group)
        info = config.get("test_information", {})
        if not isinstance(info, dict):
            raise ValueError("test_information must be a locale mapping.")
        for locale, fields in info.items():
            if not isinstance(locale, str) or not isinstance(fields, dict):
                raise ValueError("Each locale needs a field mapping.")
            if set(fields) - (set(APP_FIELDS) | {"what_to_test"}):
                raise ValueError("Unknown test information field.")
            if any(not isinstance(v, str) for v in fields.values()):
                raise ValueError("Test information values must be strings; use an empty string to clear text.")
        review = config.get("beta_review", {})
        if not isinstance(review, dict) or set(review) - {"contact_private", "demo_account_required", "notes"}:
            raise ValueError("Beta review contact values belong only in private.yaml.")
        if "demo_account_required" in review and type(review["demo_account_required"]) is not bool:
            raise ValueError("demo_account_required must be true or false.")
        if "notes" in review and not isinstance(review["notes"], str):
            raise ValueError("Beta review notes must be text.")
        self.review_attributes()

    def private_ref(self, ref):
        if not isinstance(ref, str) or not ref.startswith("testflight."):
            raise ValueError("Private references must start with testflight. and point into private.yaml.")
        node = self.private
        for key in ref.split("."):
            if not isinstance(node, dict) or key not in node:
                raise ValueError("A TestFlight private reference is missing from private.yaml.")
            node = node[key]
        return node

    def testers(self, group):
        if "testers_private" not in group:
            return []
        emails = self.private_ref(group["testers_private"])
        if not isinstance(emails, list) or any(not isinstance(x, str) or not EMAIL.fullmatch(x) for x in emails):
            raise ValueError("Private tester lists must contain email addresses only.")
        return sorted(set(x.strip().lower() for x in emails))

    def review_attributes(self):
        review = self.config.get("beta_review", {})
        result = {}
        if "contact_private" in review:
            contact = self.private_ref(review["contact_private"])
            if not isinstance(contact, dict) or set(contact) - set(CONTACT_FIELDS):
                raise ValueError("Invalid private beta review contact fields.")
            if any(not isinstance(v, str) for v in contact.values()):
                raise ValueError("Private beta review contact values must be quoted strings.")
            result.update({CONTACT_FIELDS[k]: v for k, v in contact.items()})
        for key, field in (("notes", "notes"), ("demo_account_required", "demoAccountRequired")):
            if key in review:
                result[field] = review[key]
        return result


def resolve_app(client, kit):
    bundle = kit.app.get("bundle_id")
    app_id = (kit.connect.get("api") or {}).get("app_id")
    if app_id:
        app = client.get(f"/v1/apps/{app_id}")["data"]
        if bundle and attrs(app).get("bundleId") != bundle:
            raise ValueError("api.app_id does not match facts.yaml app.bundle_id.")
        return app
    if not bundle:
        raise ValueError("Set facts.yaml app.bundle_id or connect.yaml api.app_id.")
    matches = [x for x in client.get_all("/v1/apps", {"filter[bundleId]": bundle, "limit": 200})
               if attrs(x).get("bundleId") == bundle]
    if len(matches) != 1:
        raise ValueError("Expected exactly one app matching the kit bundle ID.")
    return matches[0]


def builds(client, app_id, kit, number=None):
    params = {"filter[app]": app_id, "limit": 200, "sort": "-uploadedDate"}
    if number is not None:
        if not kit.app.get("version"):
            raise ValueError("Set facts.yaml app.version to disambiguate the build number.")
        params.update({"filter[version]": str(number),
                       "filter[preReleaseVersion.version]": str(kit.app["version"]),
                       "filter[preReleaseVersion.platform]": str(kit.app.get("platform", "IOS")).upper()})
    return client.get_all("/v1/builds", params)


def select_build(client, kit, app_id, number):
    matches = [b for b in builds(client, app_id, kit, number) if str(attrs(b).get("version")) == str(number)]
    if len(matches) != 1:
        raise ValueError("Build number must resolve to exactly one build for this app, version and platform.")
    build = matches[0]
    version = client.get(f"/v1/builds/{build['id']}/preReleaseVersion")["data"]
    if (str(attrs(version).get("version")) != str(kit.app["version"]) or
            attrs(version).get("platform") != str(kit.app.get("platform", "IOS")).upper()):
        raise ValueError("The selected build has a different version or platform.")
    if attrs(build).get("processingState") != "VALID" or attrs(build).get("expired"):
        raise ValueError("The selected build must be VALID and not expired.")
    expiry = attrs(build).get("expirationDate")
    if expiry and dt.datetime.fromisoformat(expiry.replace("Z", "+00:00")) <= dt.datetime.now(dt.timezone.utc):
        raise ValueError("The selected build has expired.")
    return build


def optional_one(client, path):
    try:
        return (client.get(path) or {}).get("data")
    except ASCError as exc:
        if exc.status == 404:
            return None
        raise


def operation(method, path, payload, label, ref=None):
    result = {"method": method, "path": path, "body": payload, "label": label}
    if ref:
        result["ref"] = ref
    return result


def upsert(ops, kind, old, wanted, rels, label, ref=None):
    if old:
        changed = {k: v for k, v in wanted.items() if attrs(old).get(k) != v}
        if changed:
            ops.append(operation("PATCH", f"/v1/{kind}/{old['id']}", body(kind, changed, rid=old["id"]), label))
    else:
        ops.append(operation("POST", f"/v1/{kind}", body(kind, wanted, rels), label, ref))


def unique(rows, key, value):
    matches = [r for r in rows if attrs(r).get(key) == value]
    if len(matches) > 1:
        raise ValueError("Ambiguous live records; resolve duplicate group names or locales before planning.")
    return matches[0] if matches else None


def distribution_plan(client, kit, number=None):
    kit.validate()
    app = resolve_app(client, kit)
    aid = app["id"]
    number = number or kit.config.get("build") or kit.app.get("build")
    build = select_build(client, kit, aid, number) if number is not None else None
    ops, warnings = [], []
    groups = client.get_all(f"/v1/apps/{aid}/betaGroups", {"limit": 200})
    desired_groups = kit.config.get("groups", [])
    if any(g["type"] == "external" for g in desired_groups) and not (
            any(attrs(g).get("isInternalGroup") for g in groups) or
            any(g["type"] == "internal" for g in desired_groups)):
        raise ValueError("Create or configure an internal group before an external group.")
    info = client.get_all(f"/v1/apps/{aid}/betaAppLocalizations", {"limit": 200})
    build_info = client.get_all(f"/v1/builds/{build['id']}/betaBuildLocalizations", {"limit": 200}) if build else []
    for locale, fields in sorted(kit.config.get("test_information", {}).items()):
        wanted = {v: fields[k] for k, v in APP_FIELDS.items() if k in fields}
        if wanted:
            upsert(ops, "betaAppLocalizations", unique(info, "locale", locale), {"locale": locale, **wanted},
                   {"app": linkage("apps", aid)}, f"Test information: {locale}")
        if "what_to_test" in fields:
            if not build:
                raise ValueError("What to Test needs a build number.")
            upsert(ops, "betaBuildLocalizations", unique(build_info, "locale", locale),
                   {"locale": locale, "whatsNew": fields["what_to_test"]},
                   {"build": linkage("builds", build["id"])}, f"What to Test: {locale}")
    review = kit.review_attributes()
    if review:
        old = optional_one(client, f"/v1/apps/{aid}/betaAppReviewDetail")
        if not old:
            raise ValueError("Beta review details are unavailable; Apple exposes PATCH, not create, for this resource.")
        # Review contact fields are always private, including values read from Apple.
        kit.pvals.extend(str(v) for k, v in attrs(old).items() if k in CONTACT_FIELDS.values() and v)
        upsert(ops, "betaAppReviewDetails", old, review, {}, "Beta review contact and notes")
    members = {g["id"]: client.get_all(f"/v1/betaGroups/{g['id']}/betaTesters", {"limit": 200}) for g in groups}
    internal_emails = {attrs(t).get("email", "").lower() for g in groups if attrs(g).get("isInternalGroup")
                       for t in members[g["id"]] if attrs(t).get("email")}
    totals = {True: set(), False: set()}
    for g in groups:
        totals[bool(attrs(g).get("isInternalGroup"))].update(
            attrs(t).get("email", "").lower() or t["id"] for t in members[g["id"]])
    new_testers = {}
    for index, group in sorted(enumerate(desired_groups), key=lambda pair: pair[1]["type"] != "internal"):
        internal = group["type"] == "internal"
        old = unique(groups, "name", group["name"])
        if old and bool(attrs(old).get("isInternalGroup")) != internal:
            raise ValueError("An existing group's internal/external type cannot be changed.")
        ref = f"@group{index}"
        gid = old["id"] if old else ref
        wanted = {"name": group["name"]}
        if not old:
            wanted.update(isInternalGroup=internal, hasAccessToAllBuilds=False)
        public = group.get("public_link", {})
        if "enabled" in public:
            wanted["publicLinkEnabled"] = public["enabled"]
        if "limit" in public:
            wanted["publicLinkLimitEnabled"] = public["limit"] is not None
            if public["limit"] is not None:
                wanted["publicLinkLimit"] = public["limit"]
        upsert(ops, "betaGroups", old, wanted, {"app": linkage("apps", aid)}, f"Group: {group['name']}", ref)
        current = {attrs(t).get("email", "").lower() for t in members.get(gid, [])}
        emails = kit.testers(group)
        totals[internal].update(emails)
        if len(totals[internal]) > (100 if internal else 10000):
            raise ValueError("Configured testers exceed the TestFlight internal/external limit.")
        for email in emails:
            if email in current:
                continue
            if internal and email not in internal_emails:
                # UNCONFIRMED: creating the first internal beta tester through this API.
                raise ValueError("Add new internal testers in App Store Connect first; only existing internal testers can be moved into additional groups here.")
            matches = [t for t in client.get_all("/v1/betaTesters", {"filter[email]": email, "limit": 200})
                       if attrs(t).get("email", "").lower() == email]
            if len(matches) > 1:
                raise ValueError("Multiple tester records match a private email; resolve them in App Store Connect.")
            tid = matches[0]["id"] if matches else new_testers.get(email)
            if tid:
                ops.append(operation("POST", f"/v1/betaGroups/{gid}/relationships/betaTesters",
                                     {"data": [linkage("betaTesters", tid)]}, f"Add private tester to {group['name']}"))
            else:
                tref = f"@tester{len(new_testers)}"
                new_testers[email] = tref
                ops.append(operation("POST", "/v1/betaTesters", body("betaTesters", {"email": email},
                                     {"betaGroups": [linkage("betaGroups", gid)]}),
                                     f"Invite private tester to {group['name']}", tref))
        if build:
            if not internal and attrs(build).get("buildAudienceType") == "INTERNAL_ONLY":
                raise ValueError("An INTERNAL_ONLY build cannot be distributed externally.")
            assigned = client.get_all(f"/v1/betaGroups/{gid}/builds", {"limit": 200}) if old else []
            if build["id"] not in {b["id"] for b in assigned}:
                ops.append(operation("POST", f"/v1/betaGroups/{gid}/relationships/builds",
                                     {"data": [linkage("builds", build["id"])]}, f"Add build {number} to {group['name']}"))
    if any(g["type"] == "external" for g in desired_groups) and build:
        state = attrs(optional_one(client, f"/v1/builds/{build['id']}/buildBetaDetail")).get("externalBuildState")
        if state not in READY:
            warnings.append(f"External build state: {state or 'unknown'}. Group assignment does not approve beta review; use plan --submit-beta then submit-beta --yes when ready.")
    return {"schema": 1, "kind": "distribution", "app_id": aid, "build": str(number) if number is not None else None,
            "build_id": build["id"] if build else None, "sources": kit.sources(), "operations": ops, "warnings": warnings}


def submission_plan(client, kit, number):
    kit.validate()
    aid = resolve_app(client, kit)["id"]
    build = select_build(client, kit, aid, number)
    bid = build["id"]
    if attrs(build).get("buildAudienceType") == "INTERNAL_ONLY":
        raise ValueError("An INTERNAL_ONLY build cannot be submitted for external beta review.")
    existing = optional_one(client, f"/v1/builds/{bid}/betaAppReviewSubmission")
    state = attrs(optional_one(client, f"/v1/builds/{bid}/buildBetaDetail")).get("externalBuildState")
    ops, warnings = [], []
    if attrs(existing).get("betaReviewState") in {"WAITING_FOR_REVIEW", "IN_REVIEW", "APPROVED"} or state in READY:
        warnings.append("This build is already submitted or ready for testing; no beta review request is needed.")
    else:
        if state != "READY_FOR_BETA_SUBMISSION":
            raise ValueError("Build is not READY_FOR_BETA_SUBMISSION; resolve processing, export compliance or review issues first.")
        peers = client.get_all("/v1/builds", {"filter[app]": aid,
            "filter[preReleaseVersion.version]": str(kit.app["version"]),
            "filter[preReleaseVersion.platform]": str(kit.app.get("platform", "IOS")).upper(), "limit": 200})
        for peer in peers:
            if peer["id"] != bid:
                submission = optional_one(client, f"/v1/builds/{peer['id']}/betaAppReviewSubmission")
                if attrs(submission).get("betaReviewState") in {"WAITING_FOR_REVIEW", "IN_REVIEW"}:
                    raise ValueError("Another build of this version is already in beta review.")
        info = client.get_all(f"/v1/apps/{aid}/betaAppLocalizations", {"limit": 200})
        if not any(attrs(x).get("description") and attrs(x).get("feedbackEmail") for x in info):
            raise ValueError("Apply a beta description and feedback email before submitting.")
        review = attrs(optional_one(client, f"/v1/apps/{aid}/betaAppReviewDetail"))
        if not all(review.get(k) for k in ("contactFirstName", "contactLastName", "contactEmail", "contactPhone")):
            raise ValueError("Apply the private beta review contact before submitting.")
        if review.get("demoAccountRequired") and not all(review.get(k) for k in ("demoAccountName", "demoAccountPassword")):
            raise ValueError("The required demo account is incomplete.")
        ops.append(operation("POST", "/v1/betaAppReviewSubmissions",
                             body("betaAppReviewSubmissions", relationships={"build": linkage("builds", bid)}),
                             f"Submit build {number} for beta review"))
    return {"schema": 1, "kind": "beta", "app_id": aid, "build": str(number), "build_id": bid,
            "sources": kit.sources(), "operations": ops, "warnings": warnings}


def plan_name(kind):
    return "testflight-beta-plan" if kind == "beta" else "testflight-plan"


def public_plan(kit, plan):
    # The envelope contains only nonsecret identifiers/hashes. Preserve schema keys
    # even when a very short password happens to occur inside a field name/hash.
    return {**plan, "operations": kit.safe(plan["operations"], mask_keys=False),
            "warnings": kit.safe(plan["warnings"])}


def save_plan(kit, plan):
    name = plan_name(plan["kind"])
    safe = public_plan(kit, plan)
    (kit.path / f"{name}.json").write_text(json.dumps(safe, indent=2, ensure_ascii=False) + "\n")
    lines = ["# TestFlight plan", "", f"App: {safe['app_id']}; build: {safe['build'] or 'none'}", "",
             "This approval covers the requests below. Tester invitations and build assignment may notify testers.", ""]
    for op in safe["operations"]:
        lines += [f"## {op['label']}", "", f"{op['method']} {op['path']}", "", "```json",
                  json.dumps(op["body"], indent=2, ensure_ascii=False), "```", ""]
    lines += [f"- {w}" for w in safe["warnings"]]
    if not safe["operations"]:
        lines.append("No changes needed.")
    (kit.path / f"{name}.md").write_text("\n".join(lines) + "\n")
    kit.emit(f"Wrote {name}.md and .json: {len(plan['operations'])} request(s).")


def replace_refs(value, refs):
    if isinstance(value, dict):
        return {k: (refs.get(v, v) if k == "id" and isinstance(v, str) else replace_refs(v, refs))
                for k, v in value.items()}
    if isinstance(value, list):
        return [replace_refs(v, refs) for v in value]
    return value


def verify_write(client, op, response):
    path, data = op["path"], op["body"]["data"]
    if "/relationships/" in path:
        live = client.get_all(path, {"limit": 200})
        if not {(r["type"], r["id"]) for r in data} <= {(r["type"], r["id"]) for r in live}:
            raise ValueError("Relationship write did not match the re-read; re-plan before retrying.")
        return None
    rid = data.get("id") or (response or {}).get("data", {}).get("id")
    if not rid:
        raise ValueError("Apple did not return a resource ID; re-plan before retrying.")
    live = client.get(f"/v1/{data['type']}/{rid}")["data"]
    if any(attrs(live).get(k) != v for k, v in data.get("attributes", {}).items()):
        raise ValueError("Write did not match the re-read; re-plan before retrying.")
    for rel, expected in data.get("relationships", {}).items():
        relpath = f"/v1/{data['type']}/{rid}/relationships/{rel}"
        if isinstance(expected["data"], list):
            actual = client.get_all(relpath, {"limit": 200})
        else:
            actual = [(client.get(relpath) or {}).get("data") or {}]
        wanted = expected["data"] if isinstance(expected["data"], list) else [expected["data"]]
        if not {(r["type"], r["id"]) for r in wanted} <= {(r["type"], r["id"]) for r in actual}:
            raise ValueError("Created resource has an unexpected relationship; re-plan before retrying.")
    return rid


def write_progress(kit, plan):
    path = kit.path / cg.PROGRESS_FILE
    progress = cg.load_yaml(path) or {}
    # These keys describe this script's work, not completion of the whole guide section.
    progress.setdefault("steps", {})[f"testflight/{plan['kind']}"] = {
        "status": "done-by-owner", "date": dt.date.today().isoformat(),
        "live": {"App ID": plan["app_id"], "Build ID": plan["build_id"], "Verified requests": len(plan["operations"])},
        "note": "Applied through testflight.py with --yes; each write was re-read and matched."}
    path.write_text(cg.PROGRESS_HEADER + yaml.safe_dump(kit.safe(progress), sort_keys=False, allow_unicode=True))


def apply_plan(client, kit, kind, number=None):
    path = kit.path / f"{plan_name(kind)}.json"
    if not path.exists():
        raise ValueError("Run plan first and review its Markdown output before applying.")
    saved = json.loads(path.read_text())
    if not isinstance(saved, dict) or saved.get("schema") != 1:
        raise ValueError("Unrecognized plan format; run plan again.")
    if saved.get("sources") != kit.sources() or saved.get("kind") != kind:
        raise ValueError("Kit files changed or the plan has a different purpose; run plan again.")
    if number is not None and saved.get("build") != str(number):
        raise ValueError("Requested build differs from the saved plan; run plan again.")
    current = submission_plan(client, kit, saved["build"]) if kind == "beta" else distribution_plan(client, kit, saved["build"])
    if saved.get("applied") and not current["operations"]:
        kit.emit("The plan is already applied; no changes needed.")
        return
    if public_plan(kit, current) != {k: v for k, v in saved.items() if k != "applied"}:
        raise ValueError("Live state changed since planning; run plan again before applying.")
    refs = {}
    for raw in current["operations"]:
        if client.dry_run:
            # Symbolic IDs remain visible; avoid GETs for resources that do not exist yet.
            kit.emit("would send: " + raw["method"] + " " + raw["path"] + " " +
                     json.dumps(kit.safe(raw["body"]), ensure_ascii=False))
            continue
        path_now = "/".join(refs.get(part, part) for part in raw["path"].split("/"))
        op = {**raw, "path": path_now, "body": replace_refs(raw["body"], refs)}
        response = getattr(client, op["method"].lower())(op["path"], op["body"])
        rid = verify_write(client, op, response)
        if "ref" in op:
            refs[op["ref"]] = rid
    if client.dry_run:
        kit.emit("Dry run: no requests sent and no progress changed.")
    else:
        write_progress(kit, current)
        saved["applied"] = True
        path.write_text(json.dumps(saved, indent=2, ensure_ascii=False) + "\n")
        kit.emit(f"Verified {len(current['operations'])} request(s); updated connect-progress.yaml.")


def status(client, kit):
    aid = resolve_app(client, kit)["id"]
    kit.emit(f"TestFlight app {aid}")
    for build in builds(client, aid, kit):
        detail = attrs(optional_one(client, f"/v1/builds/{build['id']}/buildBetaDetail"))
        review = attrs(optional_one(client, f"/v1/builds/{build['id']}/betaAppReviewSubmission"))
        kit.emit(f"Build {attrs(build).get('version')} ({build['id']}): processing={attrs(build).get('processingState')}; "
                 f"beta review={review.get('betaReviewState', 'none')}; external={detail.get('externalBuildState', 'unknown')}; "
                 f"expired={attrs(build).get('expired')}; expiry={attrs(build).get('expirationDate', 'unknown')}")
    for group in client.get_all(f"/v1/apps/{aid}/betaGroups", {"limit": 200}):
        count = len(client.get_all(f"/v1/betaGroups/{group['id']}/betaTesters", {"limit": 200}))
        a = attrs(group)
        kit.emit(f"Group {a.get('name')}: {'internal' if a.get('isInternalGroup') else 'external'}; testers={count}; "
                 f"public link={a.get('publicLinkEnabled', False)}; limit={a.get('publicLinkLimit') if a.get('publicLinkLimitEnabled') else 'off'}")


def theme(comment, crash=False):
    if crash:
        return "Crashes", True
    for pattern, label, blocker in [
        (r"data loss|lost (?:my |all )?data|deleted|corrupt", "Data loss", True),
        (r"privacy|security|leak|unauthorized", "Privacy and security", True),
        (r"crash|freeze|hang|won.t (?:open|launch)|cannot (?:open|launch)", "Stability", True),
        (r"purchase|payment|subscription|restore", "Purchases", True),
        (r"log.?in|sign.?in|password|account", "Account access", False),
        (r"slow|battery|performance", "Performance", False),
        (r"voiceover|accessib|contrast|font", "Accessibility", False),
    ]:
        if re.search(pattern, comment, re.I):
            return label, blocker
    return "Other feedback", False


def feedback(client, kit, since=None):
    cutoff = dt.datetime.combine(dt.date.fromisoformat(since), dt.time(), dt.timezone.utc) if since else None
    aid = resolve_app(client, kit)["id"]
    known = {b["id"]: str(attrs(b).get("version", b["id"])) for b in builds(client, aid, kit)}
    grouped, blockers, gaps = collections.defaultdict(list), [], []
    for kind, crash in (("betaFeedbackScreenshotSubmissions", False), ("betaFeedbackCrashSubmissions", True)):
        try:
            rows = client.get_all(f"/v1/apps/{aid}/{kind}", {"limit": 200, "include": "build"})
        except ASCError as exc:
            if exc.status not in {403, 404, 405, 501}:
                raise
            gaps.append(f"{kind}: unavailable (HTTP {exc.status}); check feedback in App Store Connect.")
            continue
        for row in rows:
            a = attrs(row)
            if cutoff:
                try:
                    when = dt.datetime.fromisoformat(str(a.get("createdDate") or "").replace("Z", "+00:00"))
                    if when.tzinfo is None:
                        raise ValueError()
                except ValueError:
                    gaps.append("A feedback item has no usable timestamp; included to avoid hiding a possible blocker.")
                else:
                    if when < cutoff:
                        continue
            bid = ((row.get("relationships") or {}).get("build", {}).get("data") or {}).get("id", "unknown")
            label = f"{known.get(bid, 'unknown')} (ID {bid})"
            category, blocker = theme(a.get("comment") or "", crash)
            summary = ""
            if crash:
                try:
                    log = attrs(client.get(f"/v1/betaFeedbackCrashSubmissions/{row['id']}/crashLog").get("data")).get("logText", "")
                    # Only stable exception tokens leave memory, never raw stacks or paths.
                    codes = sorted(set(re.findall(r"\b(?:EXC_[A-Z_]+|SIG(?:ABRT|SEGV|BUS|ILL|TRAP|KILL))\b", log)))
                    summary = ", ".join(codes) if codes else "exception not classified"
                except ASCError as exc:
                    if exc.status not in {403, 404, 405, 501}:
                        raise
                    summary = f"crash log unavailable (HTTP {exc.status})"
                    gaps.append(f"Crash log for feedback {row['id']} unavailable.")
            grouped[(label, category)].append((row["id"], summary))
            if blocker:
                blockers.append(f"Build {label}: {category}, feedback {row['id']} — investigate before release.")
    lines = ["# TestFlight feedback", "", f"Since: {since or 'all available feedback'} (UTC, inclusive)", "",
             "## Release blockers", "", "Triage candidates, not confirmed defects. Resolve each against the actual build.", ""]
    lines += [f"- {x}" for x in blockers] or ["- No candidates identified in the feedback retrieved; this is not release clearance."]
    if gaps:
        lines += ["", "## Coverage gaps", ""] + [f"- {x}" for x in sorted(set(gaps))]
    for (build, category), items in sorted(grouped.items()):
        lines += ["", f"## Build {build} — {category}", "", f"{len(items)} report(s).", ""]
        lines += [f"- Feedback {rid}" + (f": {summary}" if summary else "") for rid, summary in items]
    lines += ["", "Tester identities, comments, screenshots and raw crash logs are omitted from this shareable report.",
              "Review the source feedback in App Store Connect to reproduce each issue."]
    (kit.path / "TESTFLIGHT-FEEDBACK.md").write_text(kit.safe("\n".join(lines)) + "\n")
    kit.emit(f"Wrote TESTFLIGHT-FEEDBACK.md: {sum(map(len, grouped.values()))} feedback item(s), {len(blockers)} blocker candidate(s).")
    return 1 if gaps else 0


def main(argv=None, client=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["status", "plan", "apply", "submit-beta", "feedback"])
    parser.add_argument("kit", type=pathlib.Path)
    parser.add_argument("--build")
    parser.add_argument("--submit-beta", action="store_true", help="plan a separate beta review submission")
    parser.add_argument("--since", help="feedback on or after YYYY-MM-DD (UTC)")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    for flag in ("key-id", "issuer-id", "key-path"):
        parser.add_argument("--" + flag)
    args = parser.parse_args(argv)
    if args.command in {"apply", "submit-beta"} and not args.yes:
        print("No changes sent. Review the saved plan, then pass --yes to approve this action.")
        return 2
    if args.command == "submit-beta" and not args.build:
        parser.error("submit-beta requires --build N")
    if args.submit_beta and (args.command != "plan" or not args.build):
        parser.error("--submit-beta requires plan and --build N")
    if args.since and args.command != "feedback":
        parser.error("--since is only for feedback")
    kit = None
    try:
        kit = Kit(args.kit)
        if args.since:
            dt.date.fromisoformat(args.since)
        client = client if client is not None else make_client(args, kit=args.kit, dry_run=args.dry_run)
        client.dry_run = args.dry_run
        if args.command == "status":
            status(client, kit)
        elif args.command == "plan":
            plan = submission_plan(client, kit, args.build) if args.submit_beta else distribution_plan(client, kit, args.build)
            save_plan(kit, plan)
        elif args.command in {"apply", "submit-beta"}:
            apply_plan(client, kit, "beta" if args.command == "submit-beta" else "distribution", args.build)
        else:
            return feedback(client, kit, args.since)
        return 0
    except ASCError as exc:
        # Apple error details can echo arbitrary tester/contact data not in this kit.
        print(f"App Store Connect request failed (HTTP {exc.status}). Re-read status and re-plan before retrying.")
        return 1
    except (ValueError, ConfigError, OSError, yaml.YAMLError) as exc:
        # YAML parser excerpts may themselves contain secrets; never echo them.
        if isinstance(exc, (yaml.YAMLError, OSError, ConfigError)) or kit is None:
            print("Could not read kit or API configuration. Check YAML, file access and API key settings.")
        else:
            kit.emit(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
