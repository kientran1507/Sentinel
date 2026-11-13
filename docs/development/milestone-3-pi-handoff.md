# Milestone 3 Pi Handoff

The owner requested a commit and publication at 12:00 Asia/Saigon on 2026-11-13.
Use the published commit hash reported by that operation. Verify publication
before updating; this document alone does not establish that the push succeeded.

## Obtain the Published Source

In `~/Desktop/Sentinel`, inspect local work before pulling:

```sh
cd "$HOME/Desktop/Sentinel"
git status --short --branch
git fetch origin
git log -3 --oneline origin/codex/milestone-3-detection-engine
```

If the checkout is clean, is on `codex/milestone-3-detection-engine`, and its HEAD
is an ancestor of the published branch, update with:

```sh
git pull --ff-only origin codex/milestone-3-detection-engine
```

If there are local edits, untracked collisions, another active branch, or divergent
history, preserve them and report the condition. Do not reset, clean, discard,
automatically stash, merge, or rebase that checkout. A separate review clone is
available when the following target does not exist:

```sh
git clone --single-branch --branch codex/milestone-3-detection-engine \
  https://github.com/kientran1507/Sentinel.git \
  "$HOME/Sentinel-m3-noon-review-20261113"
```

Verify the new checkout's HEAD against the reported published hash. Updating a
checkout does not update the running image. Preserve the accepted runtime image,
scope `default`, PostgreSQL, protected configuration, `.env`, and bot consumers.
No deployment, package installation, capture, firewall change, or live login
test is authorized by fetching the source.

## Available Tooling and Verified Evidence

- `scripts.evaluate_activity` compares labelled scenarios in separate in-memory
  SQLite databases without loading `.env` or connecting to deployed storage.
- `scripts.validate_host_recovery` previews by default. Apply writes labelled
  synthetic records and remains a separately approved test operation.
- `scripts.validate_detection` provides controlled five-rule acceptance.
- Watch summaries retain cumulative source status, rejected records, and buffer
  drops. Source-gap tests distinguish retained-history recovery from expired gaps.
- No dedicated throughput tool is included.

The source bundle with archive SHA-256
`bf0e22566d4d48eff7eda60131e2d1572caa62f216bcac1a30e61e7030f35ec1`
passed all 679 Windows tests, including 193 PostgreSQL cases, with no skips.
The Pi operator reported manifest verification, compatible accepted dependencies,
42 offline tests, and the approved ten-scenario synthetic baseline: 57 records,
five matched findings, zero unexpected or missing findings. These results do not
close live false-positive, source attribution, or sustained-capacity acceptance.

## Continue the Acceptance Preparation

Preserve `/tmp/Sentinel-m3-acceptance-preparation-20261113` and its original
`APPROVAL_PLAN.md`. Copy artifacts to an owner-controlled durable directory,
recording checksums and preserving originals. The proposed location is
`~/sentinel-acceptance/2026-11-13/`; stop if existing destination content conflicts.

Revise the proposed isolated test plan before requesting execution approval:

1. Add init/signal handling and unconditional stop-and-verify cleanup by recorded
   container ID after timeout or interruption. Bypassing the image entrypoint
   also bypasses Tini. A timeout around the Docker client alone is insufficient.
2. Label all new resources with a unique run identity. Record IDs and verify
   ownership before attachment, faults, stopping, or removal. Existing resource
   names are blockers; volume creation can otherwise reuse an existing volume.
3. Supply `init-probe.sql`, `probe.sql`, their checksums, and the generator or
   manifest for the three pilot datasets. Verify unique IDs/collectors across
   all files and expected counts. Mount inputs read-only and separate log output.
4. Provide actual deadline, production-health, volume-size, and abort checks.
   Keep the declared total budget enforceable across all phases.

First prepare only the isolated database and six-case recovery phase for owner
review. SQL/batch pilots and actual database pausing remain pending. No actual
SSH devices, target/account/port, rejected key, connection producer, firewall
consumer, or live policy mapping has been approved. Preserve those pending states.

Milestone 3 remains open under its
[closeout checklist](milestone-3-acceptance.md#closeout-status).
