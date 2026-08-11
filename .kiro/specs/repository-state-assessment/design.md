# Design Document: Repository State Assessment

## Overview

The Repository State Assessor is a non-destructive assessment workflow, not a product change. It reads the Omni Steroid workspace, creates a byte-faithful assessment-owned execution mirror, runs only repository-defined checks that can be contained, and publishes sanitized evidence and a final report. Production code is never edited, formatted, restored, staged, stashed, reset, or cleaned.

The design uses five principles:

1. **Observe the shared workspace; execute in a mirror.** Git and filesystem state are captured from the source workspace, while commands that may write run only in a unique temporary mirror.
2. **Discover commands from current configuration.** `Makefile`, `pyproject.toml`, `package.json`, `vite.config.ts`, Cargo manifests, Tauri configuration, packaging documentation, workflows, and Playwright sources are read before selecting commands.
3. **Fail closed on side effects and egress.** A check is omitted when its writes, process cleanup, local prerequisites, or non-loopback network behavior cannot be contained.
4. **Classify evidence, not intent.** Every claim, check, scenario, hardware path, and parity row receives one primary status through a deterministic decision table.
5. **Publish only sanitized, referentially complete results.** Raw outputs remain in the temporary run root; only redacted records admitted by the report gate are copied to the permanent assessment-output directory.

No live External_Provider request is permitted. Existing provider credentials are neither read nor inherited. External-provider and remote-download scenarios are statically identified and omitted; dynamic provider checks use absent credentials or repository-controlled loopback fakes only.

## Goals and Non-Goals

### Goals

- Inventory material documentary claims and map each claim to current source, configuration, tests, fresh evidence, and historical evidence.
- Run fresh, terminating checks for Python, TypeScript, Rust, builds, eligible local Playwright scenarios, security/privacy controls, and available hardware/native paths.
- Preserve all pre-existing tracked and untracked work and leave production files byte-identical on success, failure, timeout, or abort.
- Produce auditable evidence records, parity matrices, status totals, ranked findings, and exact rerun procedures.

### Non-Goals

- Fixing discovered defects or documentation drift.
- Installing missing dependencies, downloading model weights, changing machine firewall policy, or altering production configuration.
- Reusing historical logs as fresh evidence.
- Executing release publication, updater checks, live cloud synthesis, provider validation, OAuth, email, calendar, contact, or telemetry endpoints.
- Running watch mode, development servers, or any process without a defined timeout and cleanup owner.

## Architecture

```text
Source Workspace (read-only intent)
  |-- Baseline Collector ----------> baseline.json + source-manifest.json
  |-- Claim Inventory -------------> claims.jsonl + search records
  |-- Command/Scenario Discovery --> verification-plan.json
  |
  +-- Snapshot Copier -----------> %TEMP%\omni-repository-assessment\<run-id>\mirror
                                      |
                                      v
                              Contained Process Runner
                              |-- write/egress policy
                              |-- fresh process + timeout
                              |-- owned PID tree
                              |-- raw stdout/stderr
                                      |
                                      v
                              Evidence Normalizer
                              |-- redaction
                              |-- status decision
                              |-- count/metric parsing
                                      |
                                      v
                              Evidence Store (temporary)
                                      |
                       +--------------+----------------+
                       |                               |
                Parity Builder                 Report Synthesizer
                       |                               |
                       +--------------+----------------+
                                      v
                     .kiro/specs/repository-state-assessment/
                       assessment-output/<run-id>/ (sanitized only)
```

The workflow is phase-gated. A later phase consumes immutable records from the prior phase; it never revises raw evidence. Corrections append a superseding record with a reason and reference to the superseded record.

### Phase A: Baseline and Safety Gate

1. Allocate a collision-resistant `run_id` and create two new locations:
   - temporary run root: `%TEMP%\omni-repository-assessment\<run-id>\`
   - permanent sanitized output: `.kiro\specs\repository-state-assessment\assessment-output\<run-id>\`
2. Capture UTC/local zoned start time, repository root, `git rev-parse HEAD`, symbolic branch or detached state, `git status --porcelain=v2 -z`, staged diff metadata, unstaged diff metadata, and untracked path names without modifying the index.
3. Record Windows edition/version/build, CPU, memory, GPU, audio endpoints, loopback endpoints, permissions that can be safely probed, and versions of tools actually selected later.
4. Build a source manifest for all pre-existing tracked and untracked paths. For production files record normalized relative path, size, and SHA-256. For sensitive files record hashes and category labels, never content.
5. Create a mirror by read-only copying the baseline files needed by discovered checks. Include staged, unstaged, and untracked content as it exists on disk; record that the Git index state is metadata and that command execution evaluates working-tree bytes. Exclude `.git` and prior assessment-output directories. Dependencies may be copied or referenced read-only only when the selected command cannot mutate them.
6. Verify every mirrored production input hash against the source manifest before executing a check. A mismatch blocks all dependent checks.

The assessor does not use `git checkout`, `git restore`, `git reset`, `git clean`, `git stash`, branch creation, worktrees, commits, or staging. It never kills a process solely because it owns a required port; a pre-existing listener makes the dependent check `Environment_Blocked`.

### Phase B: Documentary Claim Inventory and Traceability

Primary claim sources are discovered, not hard-coded, starting with the product overview, document index, architecture, features, threat model/security material, packaging/release documentation, and evidence/results documents present at baseline. Each independently verifiable statement is split into one scoped claim while preserving exact text and line location.

For each claim, the traceability mapper performs bounded searches across production source, runtime/build configuration, migrations, test sources, and workflows. It records:

- exact search terms or structural query;
- searched roots and excluded generated/dependency roots;
- every inspected candidate and why it qualifies or does not qualify;
- direct implementation, enabling/disabling configuration, and test links;
- fresh and historical evidence links;
- documentary classification: current, stale, contradictory, aspirational, unsupported, or none.

A `Not_Implemented` result requires an exhaustive documented search over all production code and configuration. Absence of a test or configuration link is represented explicitly rather than omitted. Coverage targets receive distinct line and branch claim records.

### Phase C: Verification-Plan Discovery

The planner creates one `CheckPlan` per scoped command or procedure. It resolves the command from current repository sources and stores the source location and source hash. Current known paths, subject to rediscovery at run time, are:

| Plane | Repository-defined path |
| --- | --- |
| Python lint | `uv run ruff check .` from `Makefile` / CI |
| Python types | `uv run mypy` from `Makefile` / CI; strict scope from `pyproject.toml` |
| Python tests | `uv run pytest`; default marker excludes `live_stt` |
| Python coverage | `.coveragerc` with branch measurement; ad-hoc `pytest-cov`/`coverage` tooling documented there |
| TypeScript types | `pnpm run typecheck` resolving to `tsc --noEmit` |
| TypeScript tests | `pnpm run test` resolving to `vitest run` |
| TypeScript coverage | run only if a repository-defined coverage provider/path is discovered; otherwise `Not_Implemented` after search |
| Rust | `cargo check --locked` and `cargo test --locked` in `apps/ui/src-tauri` |
| Engine build | documented PyInstaller command using `packaging/omni-engine.spec` |
| Frontend build | `pnpm run build` |
| Desktop build | host-supported targets from `tauri.conf.json`, release workflow, and packaging docs; Windows invocation passes through `cmd.exe` and the documented MSVC environment |
| Local E2E | `pnpm exec playwright test --config e2e/playwright.config.ts --project=e2e`, filtered to eligible scenario titles |

Discovery records exact executable resolution and versions (`uv`, Python, Ruff, mypy, pytest, coverage tools, Node, pnpm, TypeScript, Vitest, Playwright/browser, Rust/Cargo, Tauri CLI, PyInstaller, and native build tools). Missing tools are not installed by the assessment.

### Phase D: Contained Execution

Every selected command starts as a new non-watch process in the mirror with a per-check timeout. The runner uses Windows-safe argument arrays and explicit working directories; it does not emulate `cd` chains. Where the repository requires the MSVC batch environment, the outer invocation is `cmd.exe /d /s /c "call <setup_x64.bat> && <command>"` with quoted absolute paths because the workspace contains a space.

The child environment is allowlisted and records variable names, never secret values. At minimum it:

- forces `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8`;
- clears provider API keys, OAuth tokens, proxy credentials, and inherited `.env` discovery;
- sets `HOME`, `USERPROFILE`, `APPDATA`, `LOCALAPPDATA`, `TEMP`, and `TMP` to assessment-owned directories where compatible;
- redirects `UV_CACHE_DIR`, Python caches, coverage files, npm/pnpm stores, Vite outputs, `CARGO_HOME` when safe, `CARGO_TARGET_DIR`, Rust temp files, Playwright output, database, models, vault, and application data to the run root or mirror;
- uses lockfiles and offline/frozen modes when the repository-defined command permits them without changing semantics;
- disables E2E engine reuse and any watch behavior.

Before launch, `WritePolicy` evaluates declared and discovered outputs. If a command would write to the source workspace, a pre-existing path, user profile, real vault, real database, clipboard/desktop without an approved native procedure, or an unredirectable cache, it is omitted. The omission record lists affected paths and dependent checks.

Each process is assigned an ownership token and tracked by PID, creation time, executable path, and descendant relationship. A Windows Job Object is preferred for kill-on-close containment; otherwise the runner records a child-tree snapshot and terminates only matching owned PIDs. Cleanup runs in `finally` after success, failure, timeout, cancellation, and assessor crash recovery. PID reuse is guarded by creation time. Pre-existing processes are never restarted or killed.

A write auditor records filesystem events for the owned process tree when an available local facility can do so without system mutation. The source workspace is also hashed before and after every phase. If complete write containment cannot be established for a command, the command is omitted rather than weakening the preservation guarantee.

### Verification Planes

#### Python Engine

Lint, strict typing, tests, and coverage run as separate records so one failure does not erase other evidence. Hardware markers and any test that can reach an External_Provider are excluded by repository marker/path inspection and runtime containment. Coverage JSON is written to the run root; line and branch percentages are parsed separately and compared independently with 90% and 85%. Passed, failed, skipped, deselected, ignored, warnings, and collection errors remain separate counts.

#### TypeScript UI

Typecheck and Vitest use the package scripts exactly once. Vitest's configured `e2e/**` exclusion is retained. Four coverage metrics are accepted only from fresh machine-readable output produced by a current repository-defined coverage path. The assessor does not add `@vitest/coverage-*`, edit `vite.config.ts`, or infer missing function/branch values.

#### Rust Tauri Shell

`cargo check --locked` and `cargo test --locked` run with a redirected target directory. Test discovery includes unit tests, doc tests, and `tests/live_notepad_injection_roundtrip.rs`. Ignored tests are inventoried; the Notepad round trip is not counted as passing in the normal suite and is considered separately under native integration after preflight.

#### Product Build and Packaging/Release

The build gate contains independent component records:

1. PyInstaller onedir engine build into mirror-local `packaging/dist` and `packaging/build`.
2. Frozen engine smoke boot on a free assessment-selected loopback port with assessment DB/model paths; expect `/health` 200, then stop only its owned process.
3. Production frontend build into mirror-local `apps/ui/dist`.
4. Host-supported desktop bundles derived from current Tauri configuration and host prerequisites. On Windows, NSIS/MSI are the applicable targets; macOS/Linux targets are `Not_Applicable` on this host, not failures.

Signing keys are not read. If current local configuration requires signing or an unavailable native prerequisite, record the exact blocker. No release upload, updater request, tag, or publication occurs. The aggregate Product Build status is `Fresh_Failure` if any required applicable component executes and fails.

#### Local Playwright E2E

The scenario inventory is parsed from `apps/ui/e2e/playwright.config.ts` and every configured `.spec.ts` test. Each title receives exactly one disposition before execution. Current source inspection shows that Ask synthesis tests and the answered-Ask accessibility scenario require Gemini; onboarding model download may require remote downloads. These are excluded unless source changes make them fully local. The media project is outside Local E2E because current configuration selects it separately and it writes showcase media.

Eligible scenarios use the production frontend build/preview and real local Python engine from the repository harness. The assessment supplies:

- `OMNI_E2E_ALLOW_NO_KEYS=1`;
- an assessment-owned nonexistent/empty `OMNI_ENV_FILE`;
- no provider key variables;
- `OMNI_E2E_REUSE_ENGINE` unset and CI-style no-reuse behavior;
- `OMNI_E2E_RUN_DIR`, database, model, report, screenshot, trace, and log paths under the run root.

Ports 8765 and 4173 are checked before launch. If either is occupied, E2E is blocked; the existing harness's port-kill behavior is never allowed to target a pre-existing owner. A scenario is run only when non-loopback egress can be denied or otherwise conclusively contained for the browser and engine without changing machine policy. Every browser, preview, engine, and descendant PID is owned and cleaned. Failure records include scenario, frontend, engine, browser output, screenshot/trace paths, or explicit absence.

#### Hardware and Native Integration

Each check has an independent preflight, bounded procedure, status, and evidence record: microphone, loopback, GPU/model, dense retrieval, STT accuracy, Tauri/sidecar, tray, global hotkey, and text injection. Preflight never opens a device or executes scoped behavior; it confirms device/model/driver/permission/facility availability. Missing prerequisites produce `Environment_Blocked`, not product failures.

Live checks use only synthetic, non-private input and the requirement time bounds. Microphone capture is performed only with explicit non-private test audio and must not persist audio. Loopback uses a generated local tone. GPU inference executes exactly once. Dense retrieval separately records dense and fallback tiers. WER is emitted only with a labelled local corpus and model and is never clamped or treated as absent when zero. The ignored Rust Notepad integration runs only after desktop, Notepad, clipboard, and foreground-control preflight; because its current cleanup targets all Notepad processes, it is omitted if any pre-existing Notepad process exists.

#### Security and Privacy

Static inspection and existing hermetic tests assess local storage, telemetry absence, key custody, kill switch, approval-before-execute, Gmail draft-only behavior, append-only audit, and managed vault regions as separate controls. Dynamic refusal tests receive synthetic inputs, absent credentials or rejecting loopback fakes, and disposable state. Each control records `hermetic`, `mocked`, `local_loopback`, `hardware_backed`, and `static_only` booleans.

No historical live-provider measurement is rerun. Network observations, credential-absence evidence, local-fake request counts, action state, and pre/post disposable data hashes establish zero provider requests and side effects.

## Components and Interfaces

### `BaselineCollector`

```text
collect(repository_root) -> AssessmentBaseline
compare(baseline_manifest, final_manifest) -> WorkspaceComparison
```

Reads Git and OS state without modifying either. `compare` runs on every termination path and includes pre-existing tracked paths, pre-existing untracked paths, production hashes, and detected writes outside designated roots.

### `ClaimInventory`

```text
extract(document_sources) -> list[DocumentaryClaim]
trace(claim, search_scope) -> ClaimTrace
classify(trace, evidence_set) -> ClaimDecision
```

Exact claim text is immutable. Normalized scope is separate from quoted text. Human review remains required for materiality, independent verifiability, and ambiguous aspirational language.

### `VerificationPlanner`

```text
discover(repository_config, host) -> list[CheckPlan]
admit(check_plan, write_policy, network_policy) -> AdmissionDecision
```

Discovery sources and hashes make commands auditable. Admission is fail closed and has no `force` option.

### `ContainedProcessRunner`

```text
run(admitted_plan, run_context) -> RawExecutionResult
cancel(check_id) -> CleanupResult
recover(run_manifest) -> CleanupResult
```

The runner captures exact executable and arguments rather than a lossy display string. The display command is additionally rendered in Windows/cmd-safe form for reruns.

### `EvidenceNormalizer`

```text
normalize(raw_result, plan, baseline) -> EvidenceRecord
redact(record) -> SanitizedEvidenceRecord
validate(record) -> ValidationResult
```

Normalization parses counts and metrics but retains raw output references. Redaction occurs before permanent persistence. Validation rejects records missing required fields.

### `StatusDecider`

```text
decide(scope, applicability, path_search, prerequisites, fresh, historical) -> StatusDecision
```

Decision order:

1. `Not_Applicable` when host/config scope does not apply.
2. `Not_Implemented` when documented exhaustive search finds no executable path.
3. `Environment_Blocked` when a named prerequisite is absent before execution.
4. For executed hardware checks: complete pass → `Verified_Working`; defined subset → `Verified_Partial`; malfunction after confirmed availability → `Integration_Failed`.
5. For executed non-hardware checks: complete pass → `Verified_Working`; allowed defined subset → `Verified_Partial`; otherwise failure → `Fresh_Failure` (including aggregate build failure).
6. With no decisive fresh result: current configuration, then current code, then documentary claims, then historical evidence determine the conclusion; historical-only support → `Historical_Only`.
7. Applicable executable/claimed path with no adequate evidence → `Unverified`.

`Verified_Partial` parent records enumerate disjoint child scopes, each with its own status, without treating child status as a second parent status.

### `ParityMatrixBuilder`

```text
select_benchmark_source(sources, baseline_time, research_permitted) -> SourceDecision
build_rows(canonical_capabilities, claim_traces, evidence) -> list[ParityRow]
```

The builder uses exact canonical sets (13 Granola rows and 16 Wispr Flow rows). Benchmark source validity is independent from Omni status. Name similarity never contributes evidence.

### `ReportSynthesizer`

```text
synthesize(baseline, claims, checks, parity, evidence_index) -> AssessmentReport
admit(report, sanitized_records) -> ReportAdmissionDecision
```

Admission requires schema validity, complete evidence references, reconciled counts, no sensitive content, final workspace comparison, and no unresolved duplicate primary status.

## Data Models

### Assessment Baseline

```text
AssessmentBaseline {
  run_id, commit, branch_or_detached, started_at_with_offset,
  staged_changes[], unstaged_changes[], untracked_paths[],
  os {name, version, build}, hardware[], tools[],
  source_manifest_ref, designated_roots[], mirror_manifest_ref
}
```

### Evidence Record

```text
EvidenceRecord {
  evidence_id, check_id, plane, scope,
  exact_argv[], display_command_or_numbered_procedure,
  source_command_locations[], cwd, started_at, duration_ms,
  termination {kind, exit_code, signal, timeout_ms},
  prerequisites[], environment {os, hardware, tool_versions, safe_variable_names},
  source_revision, stdout_ref, stderr_ref, relevant_output,
  warnings[], test_counts {passed, failed, skipped, deselected, ignored},
  measurements[] {name, value, unit, scope},
  artifacts[] {kind, path_or_absent}, network_observation_ref,
  process_ownership_ref, write_audit_ref, status, status_basis,
  rerun {prerequisites, command_or_procedure, expected_observable}
}
```

A preflight-blocked record still has command/procedure, start time, zero/observed duration, null exit code, environment, source revision, status, blocker, and rerun procedure.

### Claim Trace

```text
ClaimTrace {
  claim_id, exact_text, source {path, lines, document_date}, material_scope,
  implementation_links[], configuration_links[], test_links[],
  search_evidence_refs[], fresh_evidence_refs[], historical_evidence_refs[],
  documentary_classification, primary_status, conclusion, precedence_basis
}
```

### Check Plan

```text
CheckPlan {
  check_id, plane, scope, command_source, executable, args[], cwd,
  prerequisites[], applicability, timeout_ms, declared_write_roots[],
  network_mode {none, loopback_only}, external_dependency,
  dependent_check_ids[], cleanup_procedure
}
```

### Parity Row

```text
ParityRow {
  benchmark_set, capability, benchmark_source, benchmark_source_date,
  benchmark_basis_status, omni_claim_refs[], implementation_locations[],
  fresh_evidence_refs[], primary_status, limitation, parity_conclusion,
  measurements[] {dimension, value, unit, assessed_scope, status, evidence_ref}
}
```

### Ranked Finding

```text
RankedFinding {
  rank, finding_id, category, impact, status, evidence_refs[],
  dependency_ids[], disposition: fix | validate | defer,
  completion_evidence_required
}
```

## Status and Aggregation Rules

Every classified row owns one enum-valued `primary_status`. Parent partial rows and child subset rows are different report scopes. Status totals are computed from a declared row collection, never copied from prose. The report emits the collection identifier, row count, each status count, and a checksum over sorted row IDs so totals can be independently reproduced.

Environment-blocked and external-provider-excluded scenarios are not product failures. External-provider-dependent is an E2E disposition, not an `Assessment_Status`; the associated scenario check remains omitted and is represented in scenario totals separately. Where an assessment status is required for the omitted scenario, it is `Unverified` unless a named unavailable local prerequisite independently establishes `Environment_Blocked`.

## Error Handling

- **Discovery error:** retain search/config error; do not guess a command. Classify `Not_Implemented` only after successful exhaustive search, otherwise `Unverified`.
- **Missing tool/dependency:** record detection command/output and `Environment_Blocked`; do not install it.
- **Unsafe write prediction:** omit before launch, record affected content and dependent `Unverified` checks.
- **Occupied port/pre-existing process:** do not kill or reuse it; classify dependent local integration `Environment_Blocked` with PID/port evidence redacted as needed.
- **Timeout:** terminate the owned process tree, capture output, then classify from plane and confirmed prerequisites.
- **Cleanup failure:** stop further process-launching checks, attempt bounded recovery using ownership records, and elevate a release-risk finding.
- **Unexpected non-loopback connection:** abort the owned process tree, preserve destination category (not sensitive payload), classify the check as failure or containment failure, and run cleanup/final comparison.
- **Sensitive output:** quarantine the raw artifact in the temporary root, emit a redacted replacement, and withhold the raw record from the report.
- **Source workspace mismatch:** stop all checks, preserve comparison evidence, and do not attempt restoration. Report the mismatch without modifying the affected path.
- **Interrupted assessor:** on resume, read the run manifest, clean only still-matching owned processes, mark interrupted checks `Unverified`, perform final comparison, and synthesize a partial report.

## Parity-Matrix Construction

1. Instantiate all canonical Granola and Wispr Flow rows before evidence joins.
2. Select the newest permitted benchmark source dated no later than baseline and no more than 365 days old. If research is not permitted or no source qualifies, mark only the benchmark basis `Unverified` and retain the row.
3. Join Omni claims by scoped behavior, not name similarity.
4. Join direct implementation/config/test locations and fresh evidence records.
5. Derive presence status through `StatusDecider`.
6. For latency, accuracy, reliability, and platform breadth, attach separate typed measurements. Missing measurement means that dimension is `Unverified`, even when presence is verified.
7. Derive parity conclusion from supported behavior sets and measurements; record exact supported subset and remainder for partial rows.

## Final Report Synthesis

The final Markdown report is generated from structured records and contains:

- baseline and preservation statement;
- global status totals and grand total;
- documentary claim traceability and conflict/staleness/aspiration findings;
- separate sections for all eight verification planes;
- reconciliation of 1,358 tests, 86.7% line coverage, and 78.2% branch coverage against current configuration and fresh results;
- dense retrieval and STT accuracy outcomes with explicit missing prerequisites;
- complete Granola and Wispr Flow matrices;
- security/privacy control table and verification-method booleans;
- evidence index and exact rerun instructions;
- a uniquely numbered, impact-then-dependency ordered action list with one `fix`, `validate`, or `defer` disposition per item;
- separate efficacy evidence, never inferred from tests or coverage;
- final source-workspace comparison.

Only report-relative paths point to sanitized artifacts. Temporary raw paths may be referenced by category and evidence ID but are not copied when sensitive.

## Correctness Properties

*A property is a characteristic or behavior that must hold across all valid assessment inputs and executions. The properties below focus on the assessor's pure decision, transformation, accounting, and isolation models; external tool, browser, hardware, and operating-system behavior remains integration-tested. Redundant candidate properties were consolidated so each property adds distinct validation value.*

### Property 1: Baseline records are complete and lossless

For any valid repository, environment, and tool snapshot, baseline serialization and deserialization shall preserve the commit/detached state, staged and unstaged changes, untracked paths, OS, hardware, tool versions, and zoned start time, including explicitly empty collections.

**Validates: Requirements 1.1**

### Property 2: Evidence precedence and conflicts are deterministic

For any scoped claim and any combination of fresh evidence, current configuration, current code, documentary claims, and historical evidence, the selected conclusion shall come from the highest available applicable tier; if values conflict, the conflict record shall contain every value, source, known-or-unknown date, selected conclusion, and precedence basis.

**Validates: Requirements 1.2, 1.3, 2.5, 2.6, 2.7, 7.6**

### Property 3: Assessment execution is non-destructive

For any source workspace manifest, generated tracked/untracked fixture tree, admitted or rejected operation sequence, and termination mode (success, failure, timeout, abort), all pre-existing source paths and production byte hashes shall remain identical, every observed write shall be under the current run's designated roots, unsafe operations shall be omitted with complete omission evidence, and a final comparison shall be produced.

**Validates: Requirements 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 3.17, 9.14**

### Property 4: Missing-path and documentary classifications follow evidence

For any material claim with a completed repository search, the claim decision shall be `Not_Implemented` when no executable path exists regardless of documentation or history; otherwise stale, contradictory, historical-only, unsupported, and unverified classifications shall be assigned only when their defining evidence predicates hold, with all required citations.

**Validates: Requirements 2.3, 2.4, 2.5, 2.6, 2.7, 2.9, 8.7, 8.8, 8.11**

### Property 5: Verification planning is fresh, bounded, and evidence-complete

For any admitted verification check and any resulting pass, failure, timeout, abort, or preflight block, exactly one new non-watch process attempt or one documented preflight omission shall exist, and its evidence record shall contain all required command/procedure, timing, termination, environment, revision, output, status, and rerun fields.

**Validates: Requirements 3.1, 3.13, 3.14, 3.15**

### Property 6: Aggregate build status is fail-closed

For any set of applicable required Product Build component results, the aggregate shall be `Fresh_Failure` if at least one required component executes and returns a non-passing result; otherwise the aggregate shall never hide an unclassified or missing required component, and every component shall retain its own result.

**Validates: Requirements 3.10, 3.11, 8.4**

### Property 7: Test counts and measurements do not conflate outcomes

For any valid runner output containing passes, failures, skips, deselections, ignores, warnings, and coverage metrics, normalization shall preserve each category separately, shall never include skipped/deselected/ignored tests in the passing count, and shall retain each required coverage dimension as a separate typed measurement.

**Validates: Requirements 3.5, 3.8, 3.16, 9.11**

### Property 8: E2E scenarios form an exhaustive, safe partition

For any discovered Playwright scenario inventory and prerequisite/configuration/provider metadata, every scenario shall receive exactly one disposition; External_Provider-dependent scenarios shall never appear in the execution set or local-product-failure totals, and every executed scenario shall have local prerequisites satisfied and a loopback-only network policy.

**Validates: Requirements 4.1, 4.5, 4.9, 4.10, 7.1, 7.2**

### Property 9: Cleanup affects only assessment-owned processes

For any pre-existing process set and any assessment-created process forest, cleanup after success, failure, timeout, or abort shall terminate every still-matching owned process and shall preserve every process not carrying the assessment ownership identity.

**Validates: Requirements 4.7, 4.8, 5.8**

### Property 10: Hardware status distinguishes absence from malfunction

For any hardware/native check with generated applicability, prerequisite, and execution outcomes, an unavailable preflight prerequisite shall produce `Environment_Blocked` with no product-failure conclusion; a malfunction after confirmed availability shall produce `Integration_Failed`; and each required hardware/native scope shall have exactly one status and one evidence reference.

**Validates: Requirements 5.5, 5.7, 5.9, 5.10, 5.11, 8.5, 8.6, 8.12**

### Property 11: STT accuracy preserves valid zero and complete context

For any valid uncapped word-error-rate measurement, including exactly `0.0`, report synthesis shall preserve the numeric value and corpus count, duration, language, model, hardware, and evidence reference; for any unmeasured result it shall omit the numeric value and retain every blocker.

**Validates: Requirements 5.6, 5.7, 9.5, 9.6**

### Property 12: Parity matrices have exact canonical shape

For any ordering of input evidence, the generated matrices shall contain each of the 13 required Granola capabilities and each of the 16 required Wispr Flow capabilities exactly once, with every required column present on every row.

**Validates: Requirements 6.1, 6.2, 6.3, 9.7**

### Property 13: Benchmark source selection is current and independent

For any baseline time and benchmark source set, source selection shall choose the most recent source not after baseline and not older than 365 calendar days; when none qualifies, only the benchmark basis shall be `Unverified` and Omni claim, implementation, evidence, and status evaluation shall continue unchanged.

**Validates: Requirements 6.4, 6.5, 6.6**

### Property 14: Parity conclusions are evidence-derived

For any parity row, changing feature-name similarity without changing linked evidence shall not change the parity conclusion; proper nonempty supported subsets shall yield `Verified_Partial` with an exact supported/remainder partition, and unmeasured quality dimensions shall remain `Unverified` independently of feature presence.

**Validates: Requirements 6.7, 6.8, 6.9, 6.10**

### Property 15: Security records are complete and sanitized

For any security-control result, the required control inventory shall contain one record per control with total boolean values for hermetic, mocked, local-loopback, hardware-backed, and static-only; for any generated secret, credential, private path/content, transcript, or audio marker, permanent artifacts shall contain only non-sensitive category labels and unsafe artifacts shall be withheld.

**Validates: Requirements 7.3, 7.4, 7.5, 7.11**

### Property 16: Refused external actions preserve state

For any synthetic external-action request under absent credentials or a rejecting loopback fake, the observable result shall be failure, non-loopback request count and provider side-effect count shall be zero, no pending action shall become executed, and all pre-existing user-data hashes shall remain unchanged.

**Validates: Requirements 7.8, 7.9, 7.10**

### Property 17: Primary statuses and totals reconcile exactly

For any hierarchy of claim, check, subset, and parity rows, each row shall have exactly one primary status; partial parents shall have exhaustive separately classified child subsets without double-counting; and the sum of all status totals shall equal the declared classified-row count.

**Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10, 8.11, 8.12, 9.1**

### Property 18: Report conclusions are traceable and actionable

For any synthesized report, every conclusion shall resolve to an evidence record or source location; every fresh or blocked reference shall include its required rerun details; finding ranks shall be unique and ordered by impact with prerequisites before dependents; and every ranked item shall have exactly one fix/validate/defer disposition and completion-evidence requirement.

**Validates: Requirements 9.8, 9.9, 9.10, 9.12, 9.13**

## Testing Strategy

The assessment process uses complementary tests; it does not use property testing to pretend that external tools or hardware are pure functions.

### Property-Based Tests

Implement the 18 properties against pure baseline serialization, path admission, evidence precedence, status classification, output parsing, redaction, parity construction, aggregation, and report synthesis. Each property runs at least 100 generated cases and carries the tag:

`Feature: repository-state-assessment, Property <number>: <property title>`

Generators emphasize Windows paths with spaces and drive letters, Unicode/cp1252-sensitive output, empty and conflicting evidence sets, timestamp boundaries, PID reuse metadata, percentage zero/boundaries, partial subsets, malformed runner summaries, secret-like strings, and dependency graphs.

### Unit and Example Tests

Use focused examples for:

- exact baseline rendering for branch and detached HEAD;
- the separate 90% line and 85% branch target records;
- aspirational wording and independently verifiable claim splitting;
- fixed report sections and reconciliation of committed 1,358 / 86.7% / 78.2% claims;
- command rendering through Windows `cmd.exe` with quoted space-bearing paths;
- redaction quarantine and explicit absent screenshot/trace markers;
- status decisions at every boundary.

### Integration and Smoke Tests

- Run each language/tool/build command once in a disposable fixture mirror and verify output routing and terminating behavior.
- Exercise success, nonzero exit, timeout, cancellation, and missing-tool paths with small fixture commands before running repository checks.
- Run eligible Playwright scenarios against the production preview and real local engine only after port, browser, process, write, and egress preflights.
- Validate Job Object/process-tree cleanup with a harmless owned child/grandchild and a separate pre-existing sentinel process.
- Run hardware/native checks only after their individual preflights and within requirement time bounds; do not repeat expensive model inference.
- Smoke-test permanent report admission with sanitized artifacts and final workspace comparison.

### Acceptance Validation

Before report publication, validate structured files against their schemas, verify all references, recalculate status totals, compare matrix capability sets, scan sanitized output for sensitive categories, and compare the final source manifest with baseline. Any failure blocks report finalization; it does not trigger a production-code repair.