<!--
Reply to App Review: the blocks rejection.py triage builds the draft from. Copy this file to KIT/rejection-reply.md
to change the wording for one app; rejection.py uses KIT/rejection-reply.md when it exists.

Rules for every reply (references/rejection-handling.md):
- Polite, short, specific: name the guideline, say exactly what changed or exactly where the reviewer finds it.
- Never claim a change the build or App Store Connect doesn't have yet. [Square brackets] are for the owner to fill
  with facts; rejection.py refuses to call a draft ready while one is left.
- One message per rejection. The Reply field takes at most 4000 characters.
- Appeals don't go in this field: they go to the App Review Board form, after a reply didn't resolve it.

Placeholders: {{app}}, {{version}}, {{submission}}, {{guideline}}, {{title}}, {{response}}, {{guidelines}},
{{contact}}. A block starts with a "## name" line and runs to the next one.
-->

## opening
Hello App Review team,

Thank you for reviewing {{app}} {{version}}{{submission}}.

## guideline
Guideline {{guideline}}{{title}}
{{response}}

## close.fix
We have made these changes in build [build number] and resubmitted it. Please let us know if anything else needs attention.

## close.metadata
We have updated the metadata in App Store Connect as described above. The build is unchanged. Please let us know if anything else needs attention.

## close.reply
We hope this clarifies how the app meets the guidelines. We are happy to provide anything else you need, including a screen recording or a call.

## close.bug-fix
This is a bug fix update for an app already on the App Store. As offered in your message, we would like this submission to be approved now, and we will resolve the issues above in our next update.

## close.appeal
We replied in App Store Connect on [date of the reply] and believe the app follows the guideline for the reasons above. We kindly ask the App Review Board to review the decision.

## signature
Best regards,
{{contact}}
