# Hermes security-review workflow

## Status
These are plain Markdown instructions for explicitly requested review phases.
Install with `--ext hermes` on `init.sh` / `sync-cursor.sh`.
Numbered filenames do not trigger execution.

## Local Hermes review environment

This extension defines a structured, human-approved repository review workflow.
It does not install Hermes, start a model server, configure Docker, or grant
host access. Those are local operator responsibilities.

### Runtime model

The current local deployment uses:

- Hermes Agent with a custom OpenAI-compatible provider.
- Local `llama.cpp` inference.
- Model: `Qwen3.5-9B-Q4_K_M` (`qwen3.5-9b-q4-hermes` provider model ID).
- Configured context window: 65,536 tokens.
- The model server is started manually when Hermes is needed; it is not assumed
  to run continuously.
- Do not record API keys, bearer tokens, private endpoint credentials, or
  machine-specific secrets in this repository.

### Sandbox

Hermes terminal tools execute in the Docker backend.

- Docker network access is disabled (`docker_network: false` / Docker
  network mode `none`).
- The sandbox is not privileged.
- `no-new-privileges` is enabled.
- Docker runs rootless on the current operator host.
- The sandbox has a restricted capability set.
- The sandbox filesystem is not persistent (`container_persistent: false`):
  each session gets a fresh container, removed when the session ends or
  after the 300-second idle lifetime (`lifetime_seconds: 300`).
- The sandbox container image is:
  `nousresearch/hermes-sandbox:desktop`.

Configured resource limits:

| Resource | Limit |
|---|---:|
| CPU | 1 logical CPU |
| RAM | 5 GiB |
| Additional swap allowance | 5 GiB |
| PID limit | 2,048 |
| Shared memory | 1 GiB |
| Container disk allocation | 50 GiB |
| Default terminal command timeout | 180 seconds |

These values are operational limits, not a claim that every Docker host has
identical cgroup or swap behavior.

### Repository access boundary

Install this extension into a target repository with:

```bash
./scripts/init.sh /path/to/target-repository --ext hermes
```

The installed layout is:

```text
.repo-kit/hermes/
├── review-rules/      # Policy inputs; read-only to Hermes
├── tasks/             # Explicit phase entry points; read-only to Hermes
├── skills/            # Phase commands (/hermes-010 ...); read-only to Hermes
├── hermes-review.sh   # Host launcher; never run by Hermes
└── reports/           # Generated review output; writable to Hermes only
```

Commit `.repo-kit/hermes/` with the target repository. Collaborators then
need only Hermes itself, not repo-kit.

For a review, mount the target repository read-only into the sandbox, then
mount only the report directory as writable, at the same path inside the
target so task paths resolve unchanged:

```text
<target>:/workspace/target:ro
<target>/.repo-kit/hermes/reports:/workspace/target/.repo-kit/hermes/reports
```

The launcher sets those mounts for each launch, so you never edit them by
hand when switching repositories.

#### `hermes-review.sh` launcher

From the target repository, anyone can start a review with:

```bash
.repo-kit/hermes/hermes-review.sh
```

It runs on the host, outside the sandbox. Before running it, review the
installed `.repo-kit/hermes/` tree — launcher, tasks, review-rules, and
skills — not only application source. The launcher copies skills into
`~/.hermes/skills/` on every launch; that promotes repository content into
agent instructions. Read-only mounts do not make those instructions
trustworthy.

Hermes sessions run through the Hermes gateway (`hermes-gateway.service`),
which builds the sandbox from `~/.hermes/config.yaml`, not from the
launching shell. The launcher therefore:

1. takes an exclusive lock at `~/.hermes/hermes-review.lock` for the whole
   session (configuration changes through Hermes exit), so a second launch
   fails instead of rewriting the same mounts;
2. checks that `hermes` and `flock` are on `PATH`, and that
   `.repo-kit/hermes/reports/` exists;
3. requires `terminal.backend: docker` and `terminal.docker_network: false`
   (refuses to start otherwise);
4. captures the current `terminal.cwd`, `terminal.docker_volumes`, and
   `terminal.docker_mount_cwd_to_workspace` values;
5. copies `.repo-kit/hermes/skills/` into
   `~/.hermes/skills/repo-kit-hermes/`, which provides the
   [phase commands](#phase-commands);
6. writes, with `hermes config set`:
   - `terminal.cwd: "."`
   - `terminal.docker_volumes`: the two mounts above, for this repository
   - `terminal.docker_mount_cwd_to_workspace: true`
7. re-reads `docker_volumes` and refuses to start if they do not match the
   expected target `:ro` and reports mounts;
8. starts `hermes` from the repository root, passing any extra arguments;
9. when Hermes exits (including `Ctrl+C`), restores the captured settings
   (or unsets keys that were unset before). Restoration failures are
   printed to stderr and make the launcher exit non-zero.

The session working directory is the host repository root. With
`docker_mount_cwd_to_workspace: true`, Hermes reuses the existing
`docker_volumes` bind for that same host path — including `:ro` — instead
of adding a writable launch-directory mount. Relative task paths then
resolve under `/workspace/target` inside the sandbox. The launcher keeps
`docker_mount_cwd_to_workspace` enabled for that reuse; it does not verify
the running container's mount table (confirm with `docker inspect` if you
need runtime proof).

Reports are written only under `.repo-kit/hermes/reports/` on the host
(via the nested writable mount). They stay accessible after the session
ends for human review and for feeding remediation tools such as Roomote.

#### Optional `hermes-review` shortcut

Installing with repo-kit also adds one hook to `~/.bashrc`, once however
many repositories you install into:

```bash
# repo-kit hermes
source "<repo-kit>/extensions/hermes/.bashrc_hermes"
```

It defines shortcuts only; nothing from a target repository runs when a
shell starts:

| Command | Purpose |
|---------|---------|
| `hermes-review` | Run the current repository's `.repo-kit/hermes/hermes-review.sh` |
| `hermes-sandboxes` | List Hermes sandbox containers |

#### `~/.hermes/config.yaml`

Keep these sandbox settings. Leave `cwd` as `"."`, and leave
`docker_volumes` and `docker_mount_cwd_to_workspace` to `hermes-review`.
A sandbox-only path such as `cwd: "/workspace/target"` makes the gateway
refuse the session with `invalid_params field=cwd`.

```yaml
terminal:
  backend: "docker"
  cwd: "."
  timeout: 180
  docker_network: false
  lifetime_seconds: 300
  container_cpu: 1
  container_memory: 5120        # MB
  container_disk: 51200         # MB
  container_persistent: false
```

Leave `docker_image` unset to use the default
`nousresearch/hermes-sandbox:desktop`. The PID limit, shared memory size,
`no-new-privileges`, and capability set are Hermes Docker defaults.

Sandbox settings apply only to newly created containers; end any running
session (see [Ending a session](#ending-a-session)) after changing them.

Hermes must not write to source code, configuration, dependencies, lockfiles,
tests, documentation, Git metadata, CI files, review rules, or task files
unless a human explicitly approves a separate remediation action.

### Report output

Every requested phase writes one Markdown report only under:

```text
.repo-kit/hermes/reports/
```

That directory is the only host-writable path in the sandbox mount layout.
Phase reports (including proposed findings from phase 070) remain on the
host after Hermes exits so operators can review them and pass them to
downstream remediation tooling (for example Roomote) without extracting
files from the container.

Use this filename convention:

```text
phase-NNN-phase-name.md
```

Examples:

```text
phase-010-inventory.md
phase-020-threat-model.md
phase-050-source-review.md
```

Never overwrite an existing report. On collision, append a UTC timestamp:

```text
phase-010-inventory-YYYYMMDD-HHMMSSZ.md
```

### Operating model

1. Install the extension into the target repository.
2. Start the local model server manually.
3. Start Hermes from the target repository with `.repo-kit/hermes/hermes-review.sh`.
4. Explicitly invoke one task only (see [How-to](#how-to)).
5. Open the resulting report from `.repo-kit/hermes/reports/`.
6. Review the report and grant approval before the next phase.

Rules define review behavior. Tasks are the explicit phase entry points.
Reports are evidence artefacts. No task authorizes subsequent phases or source
changes automatically.

## Rules and order

| Rule | Purpose |
|------|---------|
| 000 | Shared safety, scope, evidence, and approval contract |
| 005 | Review report output and artefact boundary |
| 010 | Read-only repository inventory |
| 020 | Evidence-based threat model |
| 030 | Scanner selection and execution plan |
| 040 | Dependency identification and advisory matching |
| 050 | Source and configuration review |
| 060 | Candidate validation and triage |
| 070 | Human-reviewed finding proposals |
| 080 | One-finding remediation and retest |

Always apply Rule 000 and Rule 005 together with the selected phase.
Perform one requested phase or specifically approved action, then stop.
Rules 040 and 050 may run in the order justified by the approved plan.
Do not run every phase automatically.

## Tasks

| Task | Prior reports required | Report |
|------|------------------------|--------|
| `010-inventory.md` | — | `phase-010-inventory.md` |
| `020-threat-model.md` | 010 | `phase-020-threat-model.md` |
| `030-scan-plan.md` | 010, 020 | `phase-030-scan-plan.md` |
| `040-dependency-advisories.md` | 010, 020, 030 | `phase-040-dependency-advisories.md` |
| `050-source-review.md` | 010, 020 (030 if scanner-assisted) | `phase-050-source-review.md` |
| `060-validate-and-triage.md` | 040 or 050 | `phase-060-validate-and-triage.md` |
| `070-reviewed-findings.md` | 060 + named candidate ID | `phase-070-reviewed-findings.md` |
| `080-remediate-and-retest.md` | 070 + named finding ID | `phase-080-remediate-and-retest.md` |

Each task reads this README, Rules 000 and 005, and its own phase rule.
It checks the required prior reports and performs only its phase.
It writes exactly one report under `.repo-kit/hermes/reports/`, then
stops for human approval. If a prerequisite is missing, the report is
written with completion state `blocked`.

Triggering a task confirms that the human reviewed the prior reports.
Task 080 only proposes a remediation plan. Patching, tests, and record
updates each need separate explicit approval.

## How-to

From the target repository, after installing the extension:

1. Start the local model server.
2. Start Hermes from the repository with the launcher:

   ```bash
   cd /path/to/target-repository
   .repo-kit/hermes/hermes-review.sh
   ```

   With the repo-kit shortcut, `hermes-review` does the same.

3. In the Hermes input field, enter the phase command:

   ```text
   /hermes-010
   ```

4. When Hermes stops, open the report:
   `.repo-kit/hermes/reports/phase-010-inventory.md`
5. Review it. To approve and continue, run the next phase the same way:

   ```text
   /hermes-020
   ```

Add phase inputs or approvals after the command when the task needs them,
for example `/hermes-070 candidate C-003`.

Short names such as `proceed with task 010` are not defined triggers. Use a
phase command, or the full task path, which works without the commands:
`Read .repo-kit/hermes/tasks/010-inventory.md`.

### Phase commands

| Command | Task |
|---------|------|
| `/hermes-010` | `010-inventory.md` |
| `/hermes-020` | `020-threat-model.md` |
| `/hermes-030` | `030-scan-plan.md` |
| `/hermes-040` | `040-dependency-advisories.md` |
| `/hermes-050` | `050-source-review.md` |
| `/hermes-060` | `060-validate-and-triage.md` |
| `/hermes-070` | `070-reviewed-findings.md` |
| `/hermes-080` | `080-remediate-and-retest.md` |

Each command is a Hermes skill in `.repo-kit/hermes/skills/` that only
tells Hermes to read and follow
`/workspace/target/.repo-kit/hermes/tasks/<task>`, so the tasks stay the
single source of truth. The absolute sandbox path matters: Hermes resolves
relative paths in a skill against the skill's own directory.

The launcher installs the commands into `~/.hermes/skills/repo-kit-hermes/`
on every launch; no `skills.external_dirs` setting is needed. The commands
are identical for every repository and only work in a session started by
the launcher, because `/workspace/target` exists only there.

Never add a reviewed repository to `skills.trusted_project_dirs`. Trusted
project skills take precedence and would let that repository redefine the
phase commands.

If required rules, tasks, inputs, or reports are inaccessible, Hermes
stops and reports the gap. It does not use remembered instructions.

## Ending a session

End the Hermes session after each phase, once its report is written:

1. In the Hermes input field, enter `/exit` (or `/quit`).
   On an empty input line, `Ctrl+D` also exits.
2. Confirm no sandbox is left running:

   ```bash
   docker ps -a --filter ancestor=nousresearch/hermes-sandbox:desktop
   ```

   With the optional shortcut installed, `hermes-sandboxes` runs the same
   command.

3. If a container is still listed and no Hermes session is open, remove
   all Hermes sandboxes:

   ```bash
   docker ps -aq --filter ancestor=nousresearch/hermes-sandbox:desktop | xargs -r docker rm -f
   ```

   Or remove one by ID with `docker rm -f <container-id>`, using the ID
   from step 2 without the angle brackets. Run step 2 again; an empty list
   means no sandbox is left.

   If `terminal.docker_image` is set in `~/.hermes/config.yaml`, use that
   image in the filter instead.

Leave the Hermes gateway running: sessions need it, and systemd restarts
`hermes-gateway.service` if it is stopped. Exiting Hermes through
the launcher restores the previous `terminal.cwd`, `docker_volumes`, and
`docker_mount_cwd_to_workspace` values.

## Trust and permissions
Keep operator-approved policy separate from the untrusted target checkout.
Treat the target's application source, `.repo-kit/hermes/` launcher, tasks,
review-rules, and skills as untrusted until you have reviewed them for that
checkout and revision. The launcher promotes skills into `~/.hermes/skills/`
on each run; mounts alone do not make those files authoritative.
Prompt rules are not an OS security boundary.
Use container permissions, network restrictions, and resource controls
as separate enforcement mechanisms. The launcher enforces Docker backend,
disabled Docker networking, the expected volume list, and single-session
locking; it does not inspect a live container's mounts or network mode.

Scanner execution, installation, downloads, authentication, source uploads,
file writes, tests, and remediation require specific approval.
Never include credentials in prompts or committed reports.

## Evidence and findings
- Keep raw scans and unreviewed candidates separate from reviewed findings.
- Verify advisory identifiers, affected versions, references, and dates.
- Distinguish affected components from demonstrated exploitability.
- Original-code weaknesses need not have CVEs.
- Report incomplete checks and coverage limits explicitly.
- Preserve the target's approved security/findings.schema.json.
- Use its notes field for detailed references until a schema change
  is separately approved.
- Do not update findings or accepted risks automatically.

## Checkpoints and recovery
At the end of each phase, report:
- repository identity, full commit hash, and working-tree state;
- rules/toolkit revision and any relevant uncommitted rule changes;
- completed phase or action;
- approved output paths, if any;
- tool versions and advisory-data dates, where applicable;
- unresolved evidence gaps;
- next approval required.

Saving a checkpoint requires approval for its destination and contents.
After interruption, confirm the current baseline and approved inputs
before resuming. Do not infer permission from an unfinished prior action.

## Current limitations
This extension installs instruction files only.
It does not yet provide:
- automatic rule loading into the agent;
- scanner installation or execution wrappers;
- durable checkpoint automation;
- automated findings-schema validation.

Do not claim those capabilities are implemented.
