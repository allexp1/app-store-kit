# TestFlight distribution and feedback

`scripts/testflight.py` is a standalone companion to `asc_sync.py`. Its API paths,
request attributes, relationships and filters were checked against Apple's
**App Store Connect OpenAPI 4.5.1** on 2026-10-15. No live account was used.

## Workflow

1. Copy `templates/testflight.example.yaml` to `KIT/testflight.yaml`. Use
   `facts.yaml` → `app.bundle_id`, `app.version`, `app.build` and optionally
   `app.platform` (defaults to IOS). `connect.yaml` → `api.app_id` is optional;
   if both app ID and bundle ID exist, they must match. API key resolution is the
   same as `asc_api.py`: command arguments, `ASC_*`, then `connect.yaml`.
2. Put tester email lists and beta review contact/demo values in
   **gitignored `KIT/private.yaml` only**. Public YAML contains dotted references
   such as `testflight.external_testers` and `testflight.review_contact`.
   Check `git check-ignore KIT/private.yaml` before committing. Never copy tester
   addresses into metadata, plans, review notes or a group name.
3. Read status and plan the distribution changes:

   ```sh
   python3 scripts/testflight.py status KIT
   python3 scripts/testflight.py plan KIT --build 42
   python3 scripts/testflight.py apply KIT --yes --dry-run
   python3 scripts/testflight.py apply KIT --yes
   ```

   `plan` performs GETs only and writes `testflight-plan.md` + `.json`. Review
   those files before approving. Apply covers group creation, public-link settings,
   localizations, private review details, tester invitations/membership, and adding
   the selected build to groups. These changes can notify testers. There is no
   tester/group deletion, membership removal, or automatic all-build access.
   Omitted fields remain unchanged; an empty text string clears that field.
   A public-link `limit: null` disables its limit; `enabled: false` disables the link.
4. For a build whose external state is `READY_FOR_BETA_SUBMISSION`, plan and
   approve review separately, **after** applying its test information:

   ```sh
   python3 scripts/testflight.py plan KIT --build 42 --submit-beta
   python3 scripts/testflight.py submit-beta KIT --build 42 --yes --dry-run
   python3 scripts/testflight.py submit-beta KIT --build 42 --yes
   python3 scripts/testflight.py status KIT
   ```

   This plan writes `testflight-beta-plan.md` + `.json` and targets exactly one
   build. It checks contact/demo details and beta description/feedback email, rejects
   internal-only or expired/unprocessed builds, and refuses when another build of
   the same version/platform is in review. Already submitted/approved/testable
   builds require no new request. Apple's live state controls eligibility: a later
   build can also require review. There is no assumption that later builds bypass it.
   Approval is asynchronous; status reports beta review and external testing state.
   If automatic notification is off, use App Store Connect to start testing/notify
   testers after approval. This script does not change notification policy.
5. Triage feedback:

   ```sh
   python3 scripts/testflight.py feedback KIT --since 2026-10-01
   ```

   Writes `TESTFLIGHT-FEEDBACK.md`, grouped by build ID/number and theme, with
   release-blocker candidates and crash exception summaries. `--since` is an
   inclusive UTC date applied locally after pagination; the API has no date filter
   on these collections. Missing timestamps remain in the report with a coverage
   warning. Crash/data-loss/security/stability/purchase themes are conservative
   local triage rules, not Apple verdicts or confirmed defects. Reproduce and
   resolve candidates in the source feedback before release.

Every write command exits **2 without `--yes`**, including dry runs. Dry runs print
masked requests with symbolic IDs for resources that would be created; they send
no writes and change no plans/progress. Apply re-reads live state and refuses a
changed plan. Inputs are bound by public file hashes and private file size/mtime
(not a password-derived hash); ordinary edits require re-planning. This is a
local workflow guard, not protection against deliberate file tampering. Every write
is re-read and compared before recording `testflight/distribution` or
`testflight/beta` in `connect-progress.yaml`, preserving existing steps. These
entries don't claim the whole Connect guide's TestFlight section is complete.
After partial failure, re-plan the remaining changes; never blindly replay a POST.

Public outputs mask private values and all email addresses. No raw feedback
comments, screenshots, crash stacks or tester identities are persisted. Open the
feedback IDs in App Store Connect to inspect the source. HTTP 403/404/405/501 on
feedback or crash logs produces a visible coverage gap and exit 1; authentication,
rate-limit and server failures are errors, never silently reported as zero feedback.
Other invalid configuration or stale-plan refusals exit 2; Apple errors exit 1.

## Limits and prerequisites

| Rule | Apple source |
|---|---|
| Up to **10,000 external testers per app**; public-link limits are 1–10,000. An internal group must exist before creating an external group. | [Invite external testers](https://developer.apple.com/help/app-store-connect/test-a-beta-version/invite-external-testers) |
| Up to **100 internal testers**, who must be App Store Connect users with app access. | [Add internal testers](https://developer.apple.com/help/app-store-connect/test-a-beta-version/add-internal-testers) |
| Builds are available for **90 days**. Use the API's `expired` and `expirationDate` rather than calculating from a local upload timestamp. | [TestFlight overview](https://developer.apple.com/help/app-store-connect/test-a-beta-version/testflight-overview) |
| The first external build requires full beta review; later builds of that version **might** also need review. Only one build of a version can be in review at a time. | [Invite external testers](https://developer.apple.com/help/app-store-connect/test-a-beta-version/invite-external-testers) |

The planner checks unique testers across known groups plus configured additions.
Apple enforces account-wide eligibility and the definitive app limits, including
testers outside these groups and people joining public links concurrently.

**UNCONFIRMED:** first-time provisioning of an *internal* tester using
`POST /v1/betaTesters`. The verified schema accepts an email and groups but has no
internal-user or role attribute. This script therefore requires the email to
already belong to an internal group; add new internal testers through App Store
Connect first. It never creates account users or changes their app access.

## API inventory (verified in 4.5.1)

All paths below use `/v1`; no guessed v2 resources or DELETE requests are used.

| Purpose | Requests |
|---|---|
| Resolve app/build | `GET /apps`, `/apps/{id}`, `/builds`, `/builds/{id}/preReleaseVersion` |
| Status/review eligibility | `GET /builds/{id}/buildBetaDetail`, `/builds/{id}/betaAppReviewSubmission` |
| Groups | `GET /apps/{id}/betaGroups`; `POST /betaGroups`; `GET/PATCH /betaGroups/{id}` |
| Members and build assignment | `GET /betaGroups/{id}/betaTesters`, `/betaGroups/{id}/builds`; `GET/POST /betaGroups/{id}/relationships/betaTesters`, `/betaGroups/{id}/relationships/builds` |
| Tester invitations | `GET/POST /betaTesters`; `GET /betaTesters/{id}` and `/betaTesters/{id}/relationships/betaGroups` |
| App test info | `GET /apps/{id}/betaAppLocalizations`; `POST /betaAppLocalizations`; `GET/PATCH /betaAppLocalizations/{id}` |
| What to Test | `GET /builds/{id}/betaBuildLocalizations`; `POST /betaBuildLocalizations`; `GET/PATCH /betaBuildLocalizations/{id}` (`whatsNew`) |
| Review contact/demo | `GET /apps/{id}/betaAppReviewDetail`; `GET/PATCH /betaAppReviewDetails/{id}`; no create endpoint |
| Submit beta review | `POST /betaAppReviewSubmissions` with `build` relationship; `GET /betaAppReviewSubmissions/{id}` and `/betaAppReviewSubmissions/{id}/relationships/build` |
| Verify newly created parents | `GET /betaGroups/{id}/relationships/app`, `/betaAppLocalizations/{id}/relationships/app`, `/betaBuildLocalizations/{id}/relationships/build` |
| Feedback | `GET /apps/{id}/betaFeedbackScreenshotSubmissions`, `/apps/{id}/betaFeedbackCrashSubmissions` (include `build`) |
| Crash summary source | `GET /betaFeedbackCrashSubmissions/{id}/crashLog` → `betaCrashLogs.attributes.logText` |

Primary sources: [Apple OpenAPI download](https://developer.apple.com/sample-code/app-store-connect/app-store-connect-openapi-specification.zip),
[TestFlight API](https://developer.apple.com/documentation/appstoreconnectapi/prerelease-versions-and-beta-testers),
[TestFlight feedback](https://developer.apple.com/documentation/appstoreconnectapi/testflight-feedback),
[View tester feedback](https://developer.apple.com/help/app-store-connect/test-a-beta-version/view-tester-feedback).

The endpoint shapes above are confirmed in the specification. Live role permissions,
notification timing, and eventual consistency have not been tested against an
account (**UNCONFIRMED operational behavior**). A re-read mismatch stops the command;
wait for Apple to settle, then plan again instead of retrying creation blindly.
