# Progress Tracker — Repository State Assessment, tasks 11.6 → 12

## North Star
Finish the repository-state assessment: execute task 11.6 (hardware/native checks behind
independent preflights), then 11.7 (sanitized final assessment), then 12 (final checkpoint),
without weakening a single safety control and without touching Omni production behavior.

## Authority to proceed
The user gave fresh, explicit authorization on 2026-08-08 ("read claude handoff and continue
gpt work"), satisfying step 1 of the resume sequence in
`docs/repository-state-assessment/CLAUDE-HANDOFF.md`. The stop-after-11.5 instruction is lifted.

## IN FLIGHT RIGHT NOW (post-assessment cleanup — read this first on resume)

The assessment itself is COMPLETE (see below). What remains is the 300-line-limit follow-up, which
the handoff gated behind tasks 11.6/11.7/12 and which is now unblocked.

**Re-measured 2026-08-09 — seven assessor modules exceed the hard 300-line limit:**

| File | Lines | Owner |
|---|---|---|
| `native_host_observations.py` | 356 | introduced this session |
| `native_integration_phase.py` | 345 | introduced this session |
| `observation_pipeline.py` | 339 | grown this session |
| `report_composition.py` | 323 | introduced this session |
| `baseline_collector.py` | 316 | transferred follow-up |
| `parity_matrix.py` | 314 | transferred follow-up |
| `e2e_orchestration.py` | 308 | transferred follow-up |

Watch list at 290–300: `mirror_execution_phase.py` 300, `verification_evidence.py` 299,
`baseline_models.py` 298, `repository_discovery.py` 296, `assessment_pipeline.py` 296,
`report_evidence_normalization.py` 294, `contained_process_runner.py` 293.
Test files also over: `tests/test_report_publication_phase.py` 531, `test_native_integration_phase.py` 301.

**Two subagents were dispatched and may still be running**, each splitting one file plus new
siblings, instructed NOT to touch `assessor/__init__.py` and NOT to touch any other module:
- agent A → `baseline_collector.py`
- agent B → `e2e_orchestration.py`

**Resume here:** confirm those two splits landed (check `wc -l` and run the suite), then split the
remaining five — `parity_matrix.py` plus the four introduced this session. `parity_matrix.py` is the
risky one: `build_canonical_parity_matrix` is exported from `assessor/__init__.py`, so a split there
must keep that import path working.

**Non-negotiables for this refactor:** structural split only, no behavior change, no signature
changes, every resulting file <= 300 lines, the full assessor suite must stay at **273 passed**, and
no test may be weakened to accommodate a split.

## STATUS: COMPLETE (the assessment itself)
Tasks 11.6, 11.7, and 12 are all done and independently verified. Nothing is in flight.

**Authoritative deliverable:**
`.kiro/specs/repository-state-assessment/assessment-output/task-12-20260809T002329/assessment-report.md`
(127 KB, all 19 fixed sections; `assessment-admission.json` records `admitted: true`, zero reasons.)

Verified directly, not taken from the gate: all nine phases green, source preservation confirmed
with **zero** manifest drift (0 added / 0 removed / 0 changed), 273 assessor tests passing, new
modules lint-clean and type-clean.

### Final assessment result
231 of 232 claims traced (the untraceable one is named in the artifact, not dropped); 288 classified
rows = 231 claims + 28 checks + 29 parity rows, reconciling exactly.

| Status | Count |
|---|---|
| Unverified | 248 |
| Environment_Blocked | 19 |
| Not_Implemented | 17 |
| Fresh_Failure | 2 |
| Verified_Working | 2 |
| **Integration_Failed** | **0** |

The honest headline: this repository is largely **unverified**, not verified-good. Most commands
cannot emit the empirical containment proof, `cargo`/`rustc` and PyInstaller are absent, and hermetic
security execution was never implemented. The two genuine passes are the GPU selection path and the
FTS5 keyword fallback retrieval tier. The committed values `1,358 tests`, `86.7 percent` line, and
`78.2 percent` branch are preserved verbatim while fresh evidence reports `2,198 tests`; coverage was
never freshly measured and is not presented as if it were.

### Remaining open items for the user
1. **Nothing is committed** — see the standing constraint below. The commit decision is yours.
2. **The sensitive-content gate passes by construction.** `admit_assessment_report` is called with no
   `forbidden_sensitive_values`. Nothing in this run handles secrets, so there is nothing concrete to
   forbid, but this should be a knowing decision rather than an inherited default.
3. **Superseded run directories** are left in place at your instruction (`task-11-6-20260808T231440`,
   `task-11-7-20260809T000240`, `task-11-7-20260809T001025`, `task-12-20260809T001849`, plus the older
   `docs/progress/repository-state-assessment.md`). Only `task-12-20260809T002329` is authoritative.
4. **Documentation drift found:** `pyproject.toml` calls this an "RTX 4070 box"; fresh hardware
   evidence says **RTX 3070**.
5. **Oversized modules** (the transferred follow-up, now unblocked): `baseline_collector.py` 316,
   `parity_matrix.py` 314, `e2e_orchestration.py` 308 lines. Re-measure before splitting.

### Defects found and fixed along the way (all mine, all verified fixed)
- `ObservedWriteAuditor` claimed one exclusive evidence root per run tree, so the second phase to use
  it came up unavailable and silently blocked both admissible native scopes. Each phase now owns its
  own root.
- A literal deny-all guard for `NetworkMode.NONE` also blocked CPython's `socket.socketpair`, i.e.
  the asyncio self-pipe on Windows. Narrowed to "same-process listener only" — strictly stronger than
  loopback-only, never weaker.
- The evidence index printed `unavailable prerequisite: unavailable prerequisite: ...` because a
  composite blocker sentence was pushed into a list of prerequisite names.
- **Regression I introduced late:** tightening `load_artifact` to reject non-objects broke
  `claims.json`, which is a bare JSON array. It survived a green 272-test suite because the fixtures
  wrote that file as an object. Distinct strict loaders now exist for each shape, with a test pinning
  both directions. Lesson worth keeping: a green suite over an untested boundary is not evidence.

## Checklist

- [x] R1 Re-read AGENTS.md, CLAUDE.md, `.cursor/rules/manifest.mdc`, spec tasks/design, handoff — DONE
- [x] R2 Reconcile working tree and confirm no assessor is running — DONE (tree matches handoff; no assessor process)
- [x] T11.6a Add `NATIVE_INTEGRATION` phase to `AssessmentPhase` (between `local e2e` and `normalization`) — DONE
- [x] T11.6b Implement `NetworkMode.NONE` egress containment adapter (native plans declare NONE; the only existing adapter serves LOOPBACK_ONLY, so without this every native check is blocked by a *missing* gate rather than by a host fact) — DONE (`no_egress_network_containment.py`, on the shared `python_startup_guard_containment` base)
- [x] T11.6c Implement real, non-behavioral host/mirror preflight observations for all 12 native scopes — DONE (`native_host_observations.py`)
- [x] T11.6d Implement bounded execution for scopes whose preflights pass — DONE (`native_bounded_procedures.py`, `native_integration_phase.py`)
- [x] T11.6e Tests first for the above — DONE (`tests/test_native_integration_phase.py`, 8 tests; full assessor suite 258 passed)
- [x] T11.6f Wire into `observation_pipeline` and execute a fresh run to `--phase-limit "native integration"` — DONE (authoritative run `task-11-6-20260808T232441`)
- [x] T11.6g Verify published evidence independently (trust the artifact, not the claim) — DONE, see "Task 11.6 verified result"
- [ ] T11.7 Normalization + parity + sanitized final report — TODO
- [ ] T12 Final checkpoint: full assessor suite green — TODO
- [ ] POST Re-measure the three oversized modules (see below) — TODO, only after 12

## Verified host facts (gathered 2026-08-08, read-only)
- `nvidia-smi` present on PATH; `cargo` absent; node/npm/pnpm/uv/git present.
- `.venv` present with `torch 2.11.0+cu128`, `nemo_toolkit 2.7.3`, `onnxruntime 1.27.0`,
  `pyaudiowpatch 0.2.12.8`, `sqlite_vec 0.1.9`.
- `%LOCALAPPDATA%/Omni/models` holds `parakeet-tdt-0.6b-v2.nemo` (2.4 GB) and `silero_vad.onnx`.
  **No `bge-small-en-v1.5` directory anywhere** → dense-retrieval weights genuinely absent.
- No labelled local speech corpus in the repository → STT accuracy has no admissible input.
- No pre-existing Notepad process at observation time.
- `apps/ui/src-tauri/target/release/omni-ui.exe`, `apps/ui/dist/`, and `packaging/dist/` exist in
  the source workspace but are **excluded from the assessment mirror** by recorded mirror policy.
- `build_contained_environment` redirects `OMNI_MODELS_DIR` to an empty assessment-owned directory,
  so a contained child never sees the host's real model weights. That is the control working as
  designed; it is not to be overridden.

## Decisions
- **D1 — Add a native phase rather than folding native checks into an existing phase.** The design
  treats Hardware/Native Integration as its own verification plane with its own preflights; the CLI
  phase enum simply lacked it. Existing pipeline tests are written against `tuple(AssessmentPhase)`
  generically, so the addition is ordering-safe.
- **D2 — Implement the missing `NetworkMode.NONE` containment adapter instead of relaxing native
  plans to `LOOPBACK_ONLY`.** Relaxing the policy to fit the available adapter would weaken a
  control to make execution possible, which is prohibited. Denying all egress is strictly stronger
  than the loopback adapter and reuses the identical per-lease startup-proof protocol.
- **D3 — Preflight availability is judged against the environment the check would actually execute
  in** (the verified mirror + contained environment), not against the developer's live desktop. A
  weight file that exists only outside the containment boundary is recorded as present-on-host but
  unavailable-to-the-check, with the exact reason.

- **D4 — An assessment-side launch failure or a containment denial is recorded as an omission,
  never as `Integration_Failed`.** Only a procedure that genuinely started and then misbehaved may
  be called a product failure, so the phase inspects child stderr for the containment denial marker
  and catches launch `OSError` before any status decision.

- **D5 — `NetworkMode.NONE` means "no destination outside this process", not "no sockets".**
  A literal deny-all guard also blocks CPython's `socket.socketpair`, which is how the asyncio
  self-pipe works on Windows, so no check could ever drive the product's async code. The guard now
  admits a loopback destination only when this same process is the listener. That permits strictly
  less than the loopback-only adapter — a local service on any other port stays unreachable — so it
  is a refinement, not a relaxation. Proven by a test that still denies a cross-process loopback
  connect and by one that lets `asyncio.run` proceed.

## Run 1 (task-11-6-20260808T231440) — SUPERSEDED, two defects found
Gate green through `native integration`, but the run is not the deliverable:
1. **Final source comparison did not confirm preservation.** Cause was operator error, not the
   assessor: the tracker file `docs/progress/repository-state-assessment-11-6-to-12.md` was edited
   while the run was hashing the workspace. Manifest diff shows exactly one changed path and zero
   added or removed — the assessor itself preserved everything. **Never edit the workspace during a
   run.**
2. **Both admissible scopes were blocked by an assessor defect, not a host fact.**
   `ObservedWriteAuditor` creates `<temp>/write-audit` exclusively, and the mirror-execution phase
   had already claimed it, so the native phase's auditor came up unavailable and containment
   refused to launch. Fixed by giving each phase its own evidence root
   (`observation_name="write-audit-native"`), with a regression test.

## Run 2 (task 11.6, authoritative)
- output root: `.kiro/specs/repository-state-assessment/assessment-output/<run-id>`
- temporary run root: `C:\DEV\Omni-Steroid-assessment-temp\<run-id>`
- phase limit: `native integration`
- run id: recorded below once launched

## Task 11.6 verified result — run `task-11-6-20260808T232441` (AUTHORITATIVE)
Gate `native integration` = green/completed. Evidence:
`.kiro/specs/repository-state-assessment/assessment-output/task-11-6-20260808T232441/native-integration.json`.

12 scopes, each with exactly one status and one evidence reference:
- **Verified_Working (2, genuinely executed once each)**
  - `graphics_processor_selection` — resolved through the product's own
    `engine.stt.stt_runtime_status.detect_inference_device`: device `cuda`,
    **NVIDIA GeForce RTX 3070**, compute capability 8.6, `inference_executed: false`.
  - `fallback_retrieval` — one retrieval through the product's own `HybridRrfRetriever` with the
    dense side explicitly absent: tier `fts5_bm25_keyword_only`, 3-document synthetic corpus,
    3 results, dense tier did not participate, 16 ms.
- **Environment_Blocked (10)** — every one for a named, evidenced prerequisite, never a product
  failure: microphone and loopback (no way to supply synthetic non-private audio without changing
  machine audio configuration), local model inference and STT accuracy (contained model root empty;
  downloads prohibited), dense retrieval (no `bge-small` export exists), Tauri/sidecar/tray (build
  outputs excluded from the mirror by recorded policy), global hotkey and text injection (would
  require taking input or foreground control of the live interactive session).
- **Integration_Failed: 0. Product failure scopes: 0.**

Independently re-verified rather than taken on the gate's word:
- Source manifests: 1440 entries before and after, **zero added, removed, or changed** —
  preservation confirmed.
- Write audits for both executed checks: `compliant: true`, zero writes outside designated roots
  (the fallback check's single change is its own disposable database).
- Network observations: both children emitted a valid `containment_proof`; the only attempt was the
  same-process asyncio self-pipe on `127.0.0.1`, recorded and allowed by the narrow rule in D5.
- No audio persisted, no downloads, no permission or firewall changes, no pre-existing process
  touched, and no stray `omni-ui`/`omni-engine`/`notepad` process afterwards.

### Incidental finding for the eventual report
`pyproject.toml` describes this machine as an "RTX 4070 box"; the fresh hardware evidence says
**RTX 3070**. Documentation drift, not a defect — record it, do not "fix" production configuration.

## Task 11.7 build plan (RESUME POINT — every API below is confirmed, not guessed)

**User decisions already taken (2026-08-08), do not re-litigate:**
- Parity matrices are built with `benchmark_basis_status` **unverified**. No external research, no
  network use. Omni is still fully evaluated; only the competitor comparison column is unverified.
- Superseded artifacts (`assessment-output/task-11-6-20260808T231440/` and the older
  `docs/progress/repository-state-assessment.md`) are **left exactly as they are**. The user will
  clean up. Do not delete, move, or rewrite them.

### Shape of the work
Three phase adapters, mirroring `local_e2e_phase.py` / `native_integration_phase.py`, wired into
`observation_pipeline.py` in place of the current `unreachable` actions for `NORMALIZATION`,
`PARITY`, and `REPORT` (the slice at the end of `actions` becomes `[8:]` once wired).
Suggested files, each kept under the 300-line limit:
- `report_evidence_normalization.py` — phase artifacts → `VerificationFinding` + `CitedEvidence`
- `report_parity_phase.py` — canonical matrix construction
- `report_publication_phase.py` — synthesize, admit, render, publish

### Inputs: read the published artifacts, do not thread pipeline state
All of these already exist in the run's output root and are the source of truth:
`baseline.json`, `claims.json`, `discovery.json`, `mirror-execution.json`, `local-e2e.json`,
`native-integration.json`. `AssessmentBaseline.from_dict` exists in `baseline_models.py`, so the
baseline round-trips without new deserializers.

### Confirmed API surface (from `assessor/__init__.py` exports)
- `synthesize_assessment_report(baseline=, claims=, verification_findings=, subset_rows=,
  parity_rows=, security_records=, security_evidence_refs=, actionable=, metric_reconciliations=,
  dense_retrieval=, stt_accuracy=, efficacy=, final_comparison=, schema_validated_evidence_ids=)`
- `build_canonical_parity_matrix(evidence_rows=())` — **already returns all 29 canonical rows**
  (13 Granola + 16 Wispr Flow) with no evidence supplied. This is the single biggest saving: with
  the unverified-basis decision, the parity phase is close to a one-liner plus any rows for which
  fresh evidence genuinely exists.
- `admit_assessment_report(report, forbidden_sensitive_values=())` → `.admitted`, `.reasons`
- `render_assessment_report_markdown(report)` → the sanitized Markdown
- `reconcile_committed_metrics({metric_id: (EvidenceSource, ...)})` — **raises unless the
  DOCUMENTARY tier values are exactly `1,358 tests`, `86.7 percent`, `78.2 percent`**. Fresh values
  come from `mirror-execution.json` → `reconciliation.fresh`.
- `synthesize_actionable_conclusions(conclusions, evidence, sources, finding_candidates)`
- `synthesize_stt_accuracy(word_error_rate_percent=, context=, blockers=, primary_status=,
  evidence_reference=)` — must stay `None`/blocked here; **never invent a WER, and never treat
  unmeasured as zero**.
- `search_claim_traceability(repository_root, search_terms)` + `decide_claim_trace(
  ClaimTraceDecisionInput(...))` for claim traces.

### The one performance trap
`search_claim_traceability` does a full `rglob` and reads every eligible source file **per claim**,
and `claims.json` holds **232 claims**. That is 232 full walks of the mirror. Budget for it, run it
once, and cache per-claim results into the normalization artifact rather than recomputing. Do not
"optimize" it by weakening the search bounds.

### Dense retrieval and STT now have real evidence (from 11.6)
- `DenseRetrievalReportEntry(dense_available=False, status=Environment_Blocked,
  evidence_ref=<native-integration.json>, note=...)` — and the note must say the **fallback tier was
  separately verified working**, because 11.6 executed it. Dense and fallback are reported
  separately; do not collapse them.
- STT accuracy stays `Environment_Blocked` with blockers `labelled local synthetic speech corpus`
  and `speech Local_Model`, and **no numeric WER**.

### Security records
Hermetic security execution is still not implemented (unchanged since the original handoff), so the
eight `SecurityControl` records carry `VerificationMethods(hermetic=False, mocked=False,
local_loopback=False, hardware_backed=False, static_only=True)` and an honest unverified/static
status. Do not claim hermetic verification that did not happen.

### Publication rules
Publish only admitted sanitized artifacts into the run's output root. Raw and quarantined output
stays in the temporary run root. No commit, no push. The report carries its own workspace
comparison; the pipeline still performs its mandatory final comparison on every termination path —
note that `_compare_source` writes `final-source-manifest.json` with exclusive create, so the
report phase must write its comparison under a **different** filename or it will collide.

### Hard-won operational rule
**Do not edit anything under `C:\DEV\Omni Steroid` while a run is executing.** That is what made
run 1's source comparison fail. Update this tracker before launching, then leave the tree alone.

## Standing constraint that overrides the usual commit cadence
The spec and the handoff forbid commit, push, stage, stash, reset, clean, restore, and any
destructive Git operation for this work, and require every pre-existing tracked and untracked path
to be preserved. That is more specific than the repository's general commit-at-every-gate rule, so
**nothing here is committed**. The tracker and the published evidence are the durable record; the
user decides when to commit.

## Agent ledger
No subagents dispatched. All work performed by the lead agent inline.

## Last-known gate state
Green through `local e2e` in run
`.kiro/specs/repository-state-assessment/assessment-output/task-11-5-20260731T124023-0230-r2`.
Final source comparison in that run confirmed preservation. `normalization`, `parity`, and
`report` were never reached; no sanitized final assessment exists.

## Transferred follow-up (do not action before task 12)
Re-measure, then split by responsibility if still over the 300-line limit:
`baseline_collector.py` (316), `parity_matrix.py` (314), `e2e_orchestration.py` (308).
Measured 2026-08-08. `contained_process_runner.py` is 293 and `mirror_execution_phase.py` is
exactly 300 — both within the limit; the earlier tracker's mention of the former is stale.
