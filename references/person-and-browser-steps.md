# Steps the API can't do: the browser (Claude) and the person (✋)

The App Store Connect API (`references/asc-api.md`, v4.5.1) covers texts, languages, screenshots, age rating,
accessibility, review details, builds, submission and release. Everything below is outside it. Read 2026-10-14.

## ✋ Person steps: Claude brings the browser to the button, the person presses it

The routine for every ✋ step:

1. **Go there.** Navigate the owner's Chrome to the URL below. If the page asks to sign in, stop: the owner signs in
   (including two-factor), then says "go on".
2. **Find the control** with `find` (the label below). Scroll it into view (`scroll_to`).
3. **Point at it.** Outline it so it is easy to spot. This is visual only and never clicks:
   `el.style.outline='4px solid #ff4a3d'; el.style.outlineOffset='4px'; el.scrollIntoView({block:'center'})`.
   Take a screenshot so the owner sees what you see.
4. **Say one line:** what to press, why, and what happens next. For example: "Press **View and Agree to Terms**,
   read it, then press **Agree**. Your Paid Apps agreement has a new version, and your in-app purchase can't go to review
   until it is accepted."
5. **Wait** for the owner's "done". Do not poll the page while they work in it.
6. **Check.** Reload, read the status (for example "Active" without "New Agreement Available"), record the step
   in `connect-progress.yaml` as `done-by-owner` with the live value, and carry on.

Claude never presses these controls, even if the owner asks. Say so plainly and point at the control instead.

| Step | Where (URL) | The control | Check afterwards |
|---|---|---|---|
| Sign in, two-factor | any App Store Connect page | Apple's sign-in sheet | the page loads the app list |
| Apple Developer Program License Agreement | https://appstoreconnect.apple.com/apps (banner) or https://developer.apple.com/account | "Review Agreement" / "Agree" | the banner is gone |
| Paid Apps / Free Apps agreement (new or updated) | https://appstoreconnect.apple.com/business | "View and Agree to Terms" in the Agreements table | status "Active" without "New Agreement Available" |
| Tax forms | https://appstoreconnect.apple.com/business | Tax Forms › "Set Up" / "Update" | status "Active" |
| Bank account | https://appstoreconnect.apple.com/business | Bank Accounts › "Add" | status "Active" |
| EU Digital Services Act trader status | https://appstoreconnect.apple.com/business | Compliance › Digital Services Act › "Edit" / "Set Up" | status "Active" |
| Create the App Store Connect API key (once) | https://appstoreconnect.apple.com/access/integrations/api | "Generate API Key" (Team Keys; role App Manager; Admin needed to create it), then "Download" | key listed; the `.p8` file is in `~/.appstoreconnect/private_keys/` |

### The API key, once

- Apple lets the `.p8` file be downloaded **once**. Ask the owner to move it to
  `~/.appstoreconnect/private_keys/AuthKey_<KEYID>.p8`. That is where `xcrun altool` also looks.
- Claude may read the **Key ID** and **Issuer ID** from the Integrations page (they are identifiers, not secrets) and
  write them into `KIT/connect.yaml`:
  ```yaml
  api:
    key_id: ABCDE12345
    issuer_id: 00000000-0000-0000-0000-000000000000
  ```
- Claude never opens, prints, copies or commits the `.p8` file. The scripts read it themselves.
- If several `AuthKey_*.p8` files exist, ask which one is this team's. Don't try them one by one.

## 🌐 Browser steps: Claude does them in Chrome, with a yes before each Save

| Step | Where | Notes |
|---|---|---|
| Create the app record (first release only) | https://appstoreconnect.apple.com/apps › "+" › New App | platforms, name, primary language, bundle ID, SKU, user access from `connect.yaml`. Xcode Cloud "Set Up Distribution" can also create it. |
| App Privacy labels + Publish | …/apps/<id>/distribution/privacy | the wizard is in `app-store-connect-fields.md` › Live-page corrections › App Privacy. Answers from `privacy-labels.md`. Publishing needs a yes. |
| iPhone/iPad app on Apple silicon Mac and on Apple Vision Pro | …/apps/<id>/distribution/pricing | two checkboxes under the price |
| Reset the rating summary (updates, optional) | the version page › App Store Version Release | |
| First in-app purchase: into the same submission as the version (🛑 a yes, it is Add for Review) | …/apps/<id>/distribution/iaps/<iap id> › "Add for Review", then the version page's "Add for Review" | Live 2026-10-14: the version page no longer has an In-App Purchases section; the purchase page says the first non-consumable "must be submitted with a new app version". Both land in one draft; Submit for Review is a separate yes. |
| Swap the product page header or search-results asset on the **live** version (no new version) | the live version page › Header and Search Results › Header or Search Results › Browse Assets › an approved asset › Next › **Publish** (🛑 a yes: it changes the live page at once) | Help, read 2026-10-14: https://developer.apple.com/help/app-store-connect/manage-app-information/manage-your-app-store-assets . The API route is unconfirmed (placements on approved parents return 409). |
| Product page **Preview** tool | the version page › Header and Search Results › Preview | shows header, name, description, screenshots and search asset on iPhone and iPad, per orientation and language. UI only. |
| Other regulations and permits (medical device, China ICP, Vietnam games) | App Information › App Store Regulations & Permits | only when they apply |

If the browser fails two or three times on the same step, hand the step to guide mode: give the owner the values
from `CONNECT-GUIDE.md` and record it when they say done.
