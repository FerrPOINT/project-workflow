---
name: project-workflow
description: Guidance for project workflow in an assigned workflow.
---

# Project Workflow

Use installed project-workflow step/history directly with the configured environment. Read the server-issued Workflow task key from Tracker context. Obtain the first/current step yourself before working; follow its instructions and report evidence using a stable operation key and expected state version. Use JSON stdin where a command accepts structured input. Never fabricate a receipt or execution identity. At the final step use the permitted Tracker command specified by Workflow and verify the saved result. PM completion requires the owner's exact-revision confirmation and ends at Backlog / Ready, without Analysis. Missing credentials or permissions are configuration errors, not instructions to use a local database or another token.

## Reports and stdin

Each report contains the business evidence requested by its current phase: the source request, actual owner decisions, completed work and remaining gaps, with the FULL saved document when required. Include the complete current packet, not a reference to an earlier report. Do not include API envelopes, raw CLI output, hashes, UUIDs, revision numbers, receipts or credentials in the report. Keep machine values in CLI arguments and protected operation records. Do not grade your own report or claim readiness in place of facts.

Send the report text directly on stdin, for example: printf '%s\n' 'Current business report and FULL document when required' | project-workflow --json step --task WORKFLOW_TASK_KEY --operation-key STABLE_KEY --expected-version VERSION --report -. Use the real complete report, not this placeholder. Do not create request files or script wrappers just to pass stdin. Keep the installed CLI authorization environment unchanged. Follow the current Workflow instructions for PARTIAL corrections and recovery of an unknown operation.
