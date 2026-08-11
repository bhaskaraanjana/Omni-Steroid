# Implementation Plan: Repository State Assessment

## Overview

Implement the Python-based Repository State Assessor entirely inside `.kiro/specs/repository-state-assessment/`, execute repository checks only in a unique temporary mirror, and publish only sanitized assessment-owned artifacts. The implementation follows test-driven development for pure logic and all 18 correctness properties, discovers commands from the current repository, and never installs dependencies, fixes production code, calls live external providers, commits, or pushes.

## Tasks

- [x] 1. Establish the assessment-owned package, schemas, and test fixtures
  - [x] 1.1 Create the assessor package and typed domain models
    - Add typed models for baselines, manifests, claims, plans, executions, evidence, statuses, parity rows, findings, run manifests, and workspace comparisons under the spec directory only.
    - Represent exact argument arrays, zoned times, typed measurements, process ownership, network/write policies, and one primary status per classified scope.
    - _Requirements: 1.1, 3.15, 6.3, 8.1, 9.8_
  - [x] 1.2 Create structured-artifact schemas and assessment-owned path management
    - Define schema validation for JSON/JSONL evidence and deterministic allocation of temporary run roots plus permanent `assessment-output/<run-id>/` directories.
    - Reject pre-existing paths, path traversal, writes outside designated roots, and permanent persistence of unsanitized records.
    - _Requirements: 1.4, 1.6, 1.7, 7.5, 7.11_
  - [x] 1.3 Write unit tests for model and schema boundary examples
    - Test branch versus detached HEAD rendering, explicitly empty collections, Windows paths with spaces, quoted `cmd.exe` reruns, typed zero measurements, and invalid/missing evidence fields before implementing behavior that consumes them.
    - _Requirements: 1.1, 3.15, 5.6, 9.12, 9.13_

- [x] 2. Build baseline, claim, and deterministic decision logic test-first
  - [x] 2.1 Write the property test for complete baseline round trips
    - **Property 1: Baseline records are complete and lossless**
    - Generate branch/detached snapshots, empty/non-empty change sets, Unicode paths, hardware/tool inventories, and zoned timestamps; require at least 100 cases.
    - **Validates: Requirements 1.1**
  - [x] 2.2 Implement baseline collection and manifest serialization
    - Read Git state without index mutation, collect OS/hardware/tool facts, hash pre-existing tracked and untracked files, label sensitive files without reading their content into reports, and serialize losslessly.
    - _Requirements: 1.1, 1.4, 1.9_
  - [x] 2.3 Write the property test for evidence precedence and complete conflicts
    - **Property 2: Evidence precedence and conflicts are deterministic**
    - Generate all evidence-tier combinations and conflict dates, asserting Fresh Evidence → configuration → code → documentary → historical precedence and complete conflict records; require at least 100 cases.
    - **Validates: Requirements 1.2, 1.3, 2.5, 2.6, 2.7, 7.6**
  - [x] 2.4 Write the property test for missing-path and documentary classification
    - **Property 4: Missing-path and documentary classifications follow evidence**
    - Generate exhaustive/incomplete searches and documentary predicates for stale, contradictory, historical-only, unsupported, aspirational, unverified, and not-implemented outcomes; require at least 100 cases.
    - **Validates: Requirements 2.3, 2.4, 2.5, 2.6, 2.7, 2.9, 8.7, 8.8, 8.11**
  - [x] 2.5 Implement claim inventory, bounded traceability search, and precedence decisions
    - Discover primary overview, feature, architecture, security/privacy, packaging/release, and evidence documents; split independently verifiable material claims while preserving exact text and locations.
    - Link source, configuration, tests, fresh/history evidence, and exhaustive search records; create distinct 90% line and 85% branch coverage target claims.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10_

- [ ] 3. Enforce source preservation and mirror-only execution
  - [x] 3.1 Write the property test for non-destructive execution
    - **Property 3: Assessment execution is non-destructive**
    - Generate tracked/untracked fixture trees, admitted/rejected operations, writes, and success/failure/timeout/abort terminations; assert unchanged source paths and bytes, designated-root-only writes, complete omissions, and final comparison; require at least 100 cases.
    - **Validates: Requirements 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 3.17, 9.14**
  - [x] 3.2 Implement mirror creation, write admission, auditing, and final comparison
    - Create a byte-faithful temporary execution mirror including current on-disk staged, unstaged, and untracked content while excluding `.git` and prior outputs; verify copied hashes before dependent checks.
    - Fail closed when writes cannot be redirected or audited, emit complete omission/dependency records, never restore source content, and compare source manifests on every termination path.
    - _Requirements: 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 3.17, 9.14_
  - [x] 3.3 Write fixture integration tests for preservation across termination modes
    - Exercise safe writes, predicted unsafe writes, unexpected writes, mirror mismatches, cancellation, and crash recovery against disposable source fixtures; assert no assessor cleanup touches pre-existing content.
    - _Requirements: 1.5, 1.7, 1.8, 1.9_

- [ ] 4. Discover and run fresh verification with deterministic evidence
  - [x] 4.1 Write the property test for fresh bounded evidence records
    - **Property 5: Verification planning is fresh, bounded, and evidence-complete**
    - Generate pass, nonzero, timeout, abort, and preflight-blocked results; assert one fresh terminating attempt or documented omission and all required evidence/rerun fields; require at least 100 cases.
    - **Validates: Requirements 3.1, 3.13, 3.14, 3.15**
  - [x] 4.2 Write the property test for fail-closed aggregate builds
    - **Property 6: Aggregate build status is fail-closed**
    - Generate applicable component result sets, including missing/unclassified components, and assert failures cannot be hidden while component records remain separate; require at least 100 cases.
    - **Validates: Requirements 3.10, 3.11, 8.4**
  - [x] 4.3 Write the property test for separate test counts and measurements
    - **Property 7: Test counts and measurements do not conflate outcomes**
    - Generate normal, malformed, Unicode, and cp1252-sensitive summaries; preserve pass/fail/skip/deselect/ignore/warning categories and independent coverage metrics; require at least 100 cases.
    - **Validates: Requirements 3.5, 3.8, 3.16, 9.11**
  - [x] 4.4 Implement repository command, scenario, target, and prerequisite discovery
    - Parse current `Makefile`, Python/Node/Rust/Tauri/Playwright configuration, workflows, lockfiles, packaging docs, and test sources; store source locations and hashes instead of hard-coding the design's known commands.
    - Resolve selected tools and versions without installing or downloading anything; classify a missing executable path only after a complete search and a missing named prerequisite as blocked.
    - _Requirements: 3.2, 3.3, 3.4, 3.6, 3.7, 3.9, 3.10, 3.12, 3.13_
  - [x] 4.5 Implement the contained terminating process runner
    - Launch each admitted command once with explicit argv/cwd, per-check timeout, allowlisted secret-free environment, redirected caches/data/build outputs, frozen/offline flags only when repository semantics permit, and no watch/development-server mode.
    - Track owned process trees by token/PID/creation time, terminate them in `finally`, preserve pre-existing processes, block unsafe writes and non-loopback egress, and quarantine raw output in the temporary root.
    - _Requirements: 3.1, 3.13, 3.14, 3.15, 3.17, 4.4, 4.7, 4.8, 4.10, 7.1, 7.2_
  - [x] 4.6 Implement evidence normalization, status decisions, and build aggregation
    - Parse exact test counts, warnings, coverage dimensions, component results, timings, and artifacts; produce one complete Evidence Record for executed or blocked checks.
    - Apply the deterministic status order, keep blocked checks out of product failures, compare Python line/branch targets independently, and aggregate required build components fail-closed.
    - _Requirements: 3.5, 3.8, 3.11, 3.15, 3.16, 8.1, 8.2, 8.3, 8.4, 8.6, 8.7, 8.8, 8.11, 8.12_
  - [x] 4.7 Write contained-runner integration tests with disposable commands
    - Exercise success, failure, timeout, cancellation, missing-tool, child/grandchild cleanup, sentinel-process preservation, output routing, and zero non-loopback connection behavior before repository checks run.
    - _Requirements: 3.1, 3.13, 3.14, 4.7, 4.8, 7.2_

- [ ] 5. Implement safe Local E2E inventory and execution gates test-first
  - [x] 5.1 Write the property test for exhaustive safe E2E partitioning
    - **Property 8: E2E scenarios form an exhaustive, safe partition**
    - Generate scenario/provider/config/prerequisite combinations; assert exactly one disposition, no provider-dependent execution/failure counting, and loopback-only execution eligibility; require at least 100 cases.
    - **Validates: Requirements 4.1, 4.5, 4.9, 4.10, 7.1, 7.2**
  - [x] 5.2 Write the property test for ownership-safe cleanup
    - **Property 9: Cleanup affects only assessment-owned processes**
    - Generate pre-existing and owned process forests with PID-reuse metadata and all termination modes; assert complete owned cleanup and preservation of every non-owned process; require at least 100 cases.
    - **Validates: Requirements 4.7, 4.8, 5.8**
  - [x] 5.3 Implement Playwright scenario inventory and explicit preflight admission
    - Parse every configured Playwright scenario and assign provider-dependent, configuration-excluded, environment-blocked, or executed disposition before launch.
    - Require production frontend/engine paths, browser, local data/services, free loopback ports, write containment, and enforceable non-loopback denial; never permit harness cleanup to kill an existing listener.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.9, 4.10_
  - [x] 5.4 Implement owned E2E orchestration and failure capture
    - Start only the production preview, real local engine, and configured browser in the mirror; use empty/nonexistent provider configuration and assessment-owned DB/model/report/trace paths.
    - Collect scenario/frontend/engine/browser output plus screenshot/trace paths or explicit absence, and clean only assessment-owned processes after completion or abort.
    - _Requirements: 4.2, 4.3, 4.6, 4.7, 4.8, 7.1, 7.2_
  - [x] 5.5 Write E2E harness integration tests using local fixtures
    - Verify occupied-port blocking, external-provider exclusion, production-path selection, loopback-only enforcement, artifact capture, and cleanup without making a live provider request.
    - _Requirements: 4.1, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10_

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Implement hardware and native checks behind individual preflights
  - [x] 7.1 Write the property test for absence-versus-malfunction status
    - **Property 10: Hardware status distinguishes absence from malfunction**
    - Generate applicability, prerequisite, execution, subset, and malfunction outcomes; assert preflight absence is `Environment_Blocked`, post-confirmation malfunction is `Integration_Failed`, and each native scope has one status/evidence reference; require at least 100 cases.
    - **Validates: Requirements 5.5, 5.7, 5.9, 5.10, 5.11, 8.5, 8.6, 8.12**
  - [x] 7.2 Write the property test for complete STT accuracy context
    - **Property 11: STT accuracy preserves valid zero and complete context**
    - Generate uncapped WER values including `0.0`, complete corpus/model/hardware context, and blocked measurements; preserve measured zero and omit values only when unmeasured; require at least 100 cases.
    - **Validates: Requirements 5.6, 5.7, 9.5, 9.6**
  - [x] 7.3 Implement independent hardware/native preflights and bounded procedures
    - Create separate plans and records for microphone, loopback, GPU/model, dense/fallback retrieval, STT corpus accuracy, Tauri/sidecar, tray, global hotkey, and text injection with the design's time limits.
    - Confirm devices, permissions, models, weights, host facilities, disposable targets, and absence of conflicting pre-existing apps/processes before any scoped behavior; use only synthetic non-private audio/text and never persist audio.
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 5.10, 5.11, 5.12, 5.13, 5.14_
  - [x] 7.4 Write native fixture and preflight integration tests
    - Test blocked preflights and bounded fake adapters first; verify dense fallback separation, no WER on missing inputs, exactly one GPU inference, sidecar cleanup, and omission of unsafe text-injection procedures.
    - Do not run actual hardware/native behavior in this task; reserve it for the explicitly gated assessment execution task.
    - _Requirements: 5.3, 5.4, 5.5, 5.7, 5.8, 5.9, 5.10, 5.11_

- [ ] 8. Implement hermetic security and privacy assessment test-first
  - [x] 8.1 Write the property test for complete sanitized security records
    - **Property 15: Security records are complete and sanitized**
    - Generate control results and secret/private markers; require one record per control, total method booleans, category-label redaction, and withholding of unsafe artifacts; require at least 100 cases.
    - **Validates: Requirements 7.3, 7.4, 7.5, 7.11**
  - [x] 8.2 Write the property test for state-preserving external-action refusal
    - **Property 16: Refused external actions preserve state**
    - Generate synthetic requests under absent credentials or rejecting loopback fakes; assert observable failure, zero non-loopback/provider effects, no executed transition, and unchanged pre-existing data hashes; require at least 100 cases.
    - **Validates: Requirements 7.8, 7.9, 7.10**
  - [x] 8.3 Implement security-control inventory, redaction, and hermetic probes
    - Assess each required storage, telemetry, key-custody, kill-switch, approval, Gmail-draft-only, append-only audit, and managed-vault-boundary control separately using static inspection or disposable hermetic execution.
    - Clear inherited credentials, use only absent credentials or rejecting repository-controlled loopback fakes, record all five verification-method booleans, and prohibit provider payloads or live calls.
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 7.10, 7.11_
  - [x] 8.4 Write security integration tests with synthetic state and loopback fakes
    - Verify refusal signaling, pending-action state, pre/post user-data hashes, zero egress/provider counts, artifact quarantine, and security status selection without reading real credentials.
    - _Requirements: 7.1, 7.2, 7.6, 7.7, 7.8, 7.9, 7.10, 7.11_

- [x] 9. Build complete Granola and Wispr Flow matrices test-first
  - [x] 9.1 Write the property test for exact canonical matrix shape
    - **Property 12: Parity matrices have exact canonical shape**
    - Permute input evidence and assert exactly 13 Granola rows, exactly 16 Wispr Flow rows, no duplicates, and every required column on every row; require at least 100 cases.
    - **Validates: Requirements 6.1, 6.2, 6.3, 9.7**
  - [x] 9.2 Write the property test for current independent benchmark-source selection
    - **Property 13: Benchmark source selection is current and independent**
    - Generate sources around baseline/future/365-day boundaries and research-permission states; select the newest qualifying source or mark only benchmark basis unverified while preserving Omni evaluation; require at least 100 cases.
    - **Validates: Requirements 6.4, 6.5, 6.6**
  - [x] 9.3 Write the property test for evidence-derived parity conclusions
    - **Property 14: Parity conclusions are evidence-derived**
    - Vary name similarity independently from evidence, generate proper subsets and missing quality dimensions, and assert exact partial partitions plus independent unverified measurements; require at least 100 cases.
    - **Validates: Requirements 6.7, 6.8, 6.9, 6.10**
  - [x] 9.4 Implement canonical matrix construction
    - Instantiate all required rows before joins, select only permitted current repository/research sources, and continue Omni evaluation when benchmark basis is unavailable.
    - Join claims, implementation, fresh evidence, limitations, and typed quality/latency/accuracy/reliability/platform measurements by scoped behavior rather than name similarity.
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 6.10_

- [ ] 10. Synthesize and admit an evidence-backed report test-first
  - [x] 10.1 Write the property test for unique statuses and exact totals
    - **Property 17: Primary statuses and totals reconcile exactly**
    - Generate claim/check/subset/parity hierarchies; assert one primary status per row, exhaustive partial children without double counting, exact totals, declared row count, and stable row-ID checksum; require at least 100 cases.
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10, 8.11, 8.12, 9.1**
  - [x] 10.2 Write the property test for traceable actionable conclusions
    - **Property 18: Report conclusions are traceable and actionable**
    - Generate evidence/source graphs and finding dependencies; require resolvable conclusions, complete reruns, unique impact/dependency ordering, one disposition, and completion evidence per finding; require at least 100 cases.
    - **Validates: Requirements 9.8, 9.9, 9.10, 9.12, 9.13**
  - [x] 10.3 Implement report synthesis, ranking, and admission gates
    - Generate baseline/preservation, claim traceability, all eight verification planes, status totals, security methods, complete parity matrices, evidence index, reruns, efficacy separation, ranked findings, and final workspace comparison.
    - Reconcile the committed 1,358-test, 86.7%-line, and 78.2%-branch claims against dates, current configuration, and fresh evidence; report dense/STT outcomes without inventing measurements.
    - Block finalization on invalid schemas, missing references, duplicate statuses, unreconciled totals, matrix omissions, sensitive content, or source mismatch.
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9, 9.10, 9.11, 9.12, 9.13, 9.14_
  - [x] 10.4 Write report example and admission tests
    - Test fixed sections, historical/current/fresh reconciliation, exact matrix rows, blocked reruns, explicit absent screenshot/trace markers, ranked dependency order, redaction quarantine, and admission rejection reasons.
    - _Requirements: 4.6, 6.1, 6.2, 7.11, 9.1, 9.2, 9.3, 9.7, 9.8, 9.9, 9.10, 9.12, 9.13, 9.14_

- [ ] 11. Wire, verify, and execute the assessor without changing Omni production behavior
  - [x] 11.1 Implement the phase-gated CLI and resumable run manifest
    - Wire baseline → claims → discovery/admission → mirror execution → normalization → parity → report, preserving immutable raw evidence and appending superseding records rather than rewriting it.
    - Add bounded cancellation/recovery that cleans only matching owned processes, marks interrupted checks unverified, performs final comparison, and supports a partial report.
    - _Requirements: 1.5, 1.9, 3.15, 4.7, 4.8, 8.1, 9.14_
  - [x] 11.2 Write an automated orchestration smoke test in a disposable repository fixture
    - Exercise phase gates, source mismatch stop, unsafe-write omission, egress denial, missing prerequisites, cleanup failure, report admission, and success/failure/timeout/abort final comparisons.
    - Assert the CLI creates only fixture-owned temporary/permanent artifacts and never invokes dependency installation, provider access, production repair, Git commit, or push paths.
    - _Requirements: 1.5, 1.6, 1.7, 1.8, 1.9, 3.1, 3.13, 4.10, 7.2, 9.14_
  - [x] 11.3 Execute baseline, claim inventory, command discovery, and admission planning
    - Run the assessor against the source workspace in observation-only mode, create and hash the temporary mirror, inventory all material claims/scenarios/checks, resolve current commands/tools, and record every omitted unsafe or unavailable operation.
    - Stop before process execution if mirror verification, write containment, redaction setup, source comparison, or loopback-only enforcement cannot be established.
    - _Requirements: 1.1, 1.4, 1.6, 1.7, 1.8, 2.1, 2.2, 2.3, 3.12, 3.13_
  - [x] 11.4 Execute fresh contained language, build, packaging, and security checks
    - In the verified mirror, run each discovered Python lint/type/test/coverage, TypeScript type/test/coverage, Rust check/test, applicable engine/frontend/desktop build, frozen-engine smoke, packaging, and hermetic security check as a new terminating process.
    - Do not install missing dependencies, run live-provider/release/updater paths, alter production configuration, or fix failures; retain separate evidence, counts, metrics, component results, warnings, blockers, and aggregate build status.
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 3.13, 3.14, 3.15, 3.16, 3.17, 7.1, 7.2, 7.3_
  - [x] 11.5 Execute eligible Local E2E only after all explicit preflights pass
    - Verify production build/engine/browser/local data/free ports/process ownership/write audit/loopback-only egress first; classify every scenario before launching any process.
    - Execute only fully local scenarios with production paths, capture required diagnostics, and clean owned processes; omit provider/download/config-excluded or unsafe scenarios without converting exclusions into product failures.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10_
  - [x] 11.6 Execute each hardware/native check only after its independent preflight passes
    - Run eligible microphone, loopback, GPU/model, dense/fallback retrieval, STT accuracy, Tauri/sidecar, tray, hotkey, and text-injection checks once within specified bounds using synthetic non-private inputs and disposable targets.
    - Record blocked prerequisites before scoped execution and integration failures only after confirmed availability; never download weights, change permissions/firewall, persist audio, or interfere with pre-existing applications.
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 5.10, 5.11, 5.12, 5.13, 5.14_
  - [x] 11.7 Generate, validate, and publish the sanitized final assessment
    - Build complete Granola/Wispr Flow matrices, derive all classifications and totals, synthesize the report, validate schemas/references/redaction/counts/checksums, and perform the final source-manifest comparison on every termination path.
    - Publish only admitted sanitized artifacts under the current run's assessment output; retain raw/quarantined output only in the temporary run root and make no commit or push.
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 6.10, 8.1, 8.9, 9.1, 9.2, 9.7, 9.8, 9.9, 9.10, 9.11, 9.12, 9.13, 9.14_

- [x] 12. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.
  - Assessor suite: 273 passed, 0 failed (2026-08-09). New modules lint-clean and type-clean.
  - Full pipeline run `task-12-20260809T002329`: all nine gates green, report admitted,
    source preservation confirmed with zero manifest drift.
  - Note on the product suite (assessed, not re-run here): its tests pass (2,198 passed, 0 failed,
    1 skipped, 1 deselected) but the assessment check still records a failure because the suite
    writes `unused.db` outside its designated roots. Tests passing and the containment check
    failing are separate facts and are reported separately.

## Notes

- Pure-logic unit and property tests are required rather than optional because the workspace mandates test-first implementation; every property test runs at least 100 generated cases with the design-specified feature/property tag.
- All assessor source, tests, schemas, and permanent outputs remain under `.kiro/specs/repository-state-assessment/`; command execution and raw artifacts remain in a unique temporary mirror/run root.
- No task authorizes dependency installation or downloads, live external-provider calls, production-code/configuration fixes, release publication, commits, pushes, staging, stashing, resetting, cleaning, or restoration of source files.
- E2E and hardware/native execution tasks are phase-gated: failed or inconclusive write, process, prerequisite, port, browser, permission, or loopback-egress preflight means omission/blocking rather than unsafe execution.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["1.3", "2.1", "2.3", "2.4", "3.1", "4.1", "4.2", "4.3", "5.1", "5.2", "7.1", "7.2", "8.1", "8.2", "9.1", "9.2", "9.3", "10.1", "10.2"] },
    { "id": 3, "tasks": ["2.2", "4.4", "4.6"] },
    { "id": 4, "tasks": ["2.5", "3.2", "7.3", "8.3"] },
    { "id": 5, "tasks": ["4.5", "5.3", "9.4"] },
    { "id": 6, "tasks": ["5.4", "10.3"] },
    { "id": 7, "tasks": ["3.3", "4.7", "5.5", "7.4", "8.4", "10.4"] },
    { "id": 8, "tasks": ["11.1"] },
    { "id": 9, "tasks": ["11.2"] },
    { "id": 10, "tasks": ["11.3"] },
    { "id": 11, "tasks": ["11.4"] },
    { "id": 12, "tasks": ["11.5"] },
    { "id": 13, "tasks": ["11.6"] },
    { "id": 14, "tasks": ["11.7"] }
  ]
}
```
