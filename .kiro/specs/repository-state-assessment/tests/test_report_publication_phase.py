"""Task 11.7 normalization, parity, and report-composition tests.

Adversarial by intent: normalization must project every published check into exactly
one finding with exactly one uniquely-identified evidence record, every rerun
instruction must carry exactly one executable form, a blocked or unimplemented check
must never be rendered as a product failure, and no composed report input may invent a
number that was never measured.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from assessor.assessment_phase_gates import GateStatus
from assessor.evidence_precedence import EvidenceTier
from assessor.model_types import AssessmentStatus
from assessor.report_claim_tracing import claim_search_terms
from assessor.report_composition import (
    build_dense_and_stt,
    build_metric_reconciliations,
    build_security_evidence,
)
from assessor.report_evidence_normalization import (
    normalize_local_e2e,
    normalize_mirror_execution,
    normalize_native_integration,
)
from assessor.report_publication_phase import (
    NORMALIZATION_CHECK_IDS,
    PARITY_CHECK_IDS,
    execute_normalization,
    execute_parity,
)
from assessor.security_records import SecurityControl

ENVIRONMENT = "Windows 10; baseline fixture-commit"
_FAILURE_STATUSES = frozenset(
    {AssessmentStatus.FRESH_FAILURE, AssessmentStatus.INTEGRATION_FAILED}
)


def _check(
    check_id: str,
    status: str,
    *,
    blockers: tuple[str, ...] = (),
    executed: tuple[str, ...] = (),
    discovered: tuple[str, ...] = (),
    exit_code: int | None = 0,
    counts: dict[str, int] | None = None,
) -> dict[str, object]:
    return {
        "check_id": check_id,
        "status": status,
        "blockers": list(blockers),
        "executed_argv": list(executed),
        "discovered_argv": list(discovered),
        "exit_code": exit_code,
        "test_counts": counts or {"passed": 0, "failed": 0, "skipped": 0},
    }


def _mirror_payload(
    checks: tuple[dict[str, object], ...] | None = None,
    fresh: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "checks": list(
            checks
            or (
                _check(
                    "python-lint",
                    "blocked",
                    blockers=("command cannot emit the required containment proof",),
                    discovered=("uv", "run", "ruff", "check", "."),
                ),
                _check(
                    "python-tests",
                    "failed",
                    executed=("uv", "run", "--active", "pytest"),
                    discovered=("uv", "run", "pytest"),
                    exit_code=None,
                    counts={"passed": 2198, "failed": 0, "skipped": 1},
                ),
                _check("packaging-installer", "not implemented", exit_code=None),
                _check("hermetic-security", "not implemented", exit_code=None),
            )
        ),
        "reconciliation": {
            "committed": {
                "tests": 1358,
                "line_coverage_percent": "86.7",
                "branch_coverage_percent": "78.2",
            },
            "fresh": fresh
            if fresh is not None
            else {
                "tests": {"passed": 2198, "failed": 0, "skipped": 1},
                "line_coverage_percent": None,
                "branch_coverage_percent": None,
            },
            "historical_values_preserved": True,
        },
    }


def _e2e_payload() -> dict[str, object]:
    return {
        "scenario_count": 26,
        "disposition_counts": {"environment_blocked": 19, "configuration_excluded": 7},
        "preflights": [
            {"name": "production frontend build", "status": "blocked", "reason": "production index must exist"},
            {"name": "browser binary", "status": "blocked", "reason": "no installed browser binary"},
            {"name": "loopback guard", "status": "available", "reason": "guard present"},
        ],
    }


def _scope(
    scope: str,
    status: AssessmentStatus,
    *,
    blockers: tuple[str, ...] = (),
    unavailable: tuple[str, ...] = (),
    available: tuple[str, ...] = (),
    procedure: tuple[str, ...] = ("Start the scoped procedure once",),
    result: dict[str, object] | None = None,
) -> dict[str, object]:
    preflight = [
        {"prerequisite": name, "available": False, "detection_evidence": "no enumeration performed"}
        for name in unavailable
    ] + [
        {"prerequisite": name, "available": True, "detection_evidence": "observed on host"}
        for name in available
    ]
    return {
        "scope": scope,
        "check_id": f"hardware-{scope}",
        "status": status.value,
        "blockers": list(blockers),
        "preflight": preflight,
        "numbered_procedure": list(procedure),
        "observables": [{"name": f"{scope} observable", "deadline_ms": 10_000}],
        "result": result,
    }


def _native_payload(scopes: tuple[dict[str, object], ...] | None = None) -> dict[str, object]:
    return {
        "scope_count": 3,
        "scopes": list(
            scopes
            or (
                _scope(
                    "dense_retrieval",
                    AssessmentStatus.ENVIRONMENT_BLOCKED,
                    blockers=("unavailable prerequisite: dense embedding weights",),
                    unavailable=("dense embedding weights",),
                ),
                _scope(
                    "fallback_retrieval",
                    AssessmentStatus.VERIFIED_WORKING,
                    available=("index fixture",),
                    result={"matched": 3},
                ),
                _scope(
                    "stt_accuracy",
                    AssessmentStatus.ENVIRONMENT_BLOCKED,
                    blockers=("unavailable prerequisite: labelled speech corpus",),
                    unavailable=("labelled speech corpus", "speech model weights"),
                    available=("synthetic audio fixture",),
                ),
            )
        ),
    }


def _baseline_payload() -> dict[str, object]:
    return {
        "run_id": "task-11-7-fixture",
        "repository_root": "C:/DEV/fixture",
        "head": {"commit": "fixture-commit", "kind": "branch", "branch_name": "main"},
        "started_at": "2026-08-08T23:24:49.774687-02:30",
        "staged_changes": [],
        "unstaged_changes": [],
        "untracked_paths": [],
        "operating_system": {"name": "Windows", "version": "10", "build": "10.0.26200"},
        "hardware": [],
        "tools": [],
        "source_manifest_ref": "source-manifest.json",
        "designated_roots": ["C:/DEV/fixture-output"],
        "mirror_manifest_ref": None,
    }


def _output_root(
    tmp_path: Path,
    mirror: dict[str, object] | None = None,
    native: dict[str, object] | None = None,
) -> Path:
    root = tmp_path / "output"
    root.mkdir()
    for name, payload in (
        ("baseline.json", _baseline_payload()),
        ("mirror-execution.json", mirror or _mirror_payload()),
        ("local-e2e.json", _e2e_payload()),
        ("native-integration.json", native or _native_payload()),
    ):
        (root / name).write_text(json.dumps(payload), encoding="utf-8")
    return root


def _normalized(root: Path) -> dict[str, object]:
    return json.loads((root / "normalized-evidence.json").read_text(encoding="utf-8"))


def test_normalization_projects_every_check_into_one_finding_and_unique_evidence(
    tmp_path: Path,
) -> None:
    root = _output_root(tmp_path)

    result = execute_normalization(root)

    assert result.gate is GateStatus.GREEN
    assert [item.check_id for item in result.checks] == list(NORMALIZATION_CHECK_IDS)
    assert all(item.verified for item in result.checks)
    payload = _normalized(root)
    findings = payload["findings"]
    evidence = payload["evidence"]
    # four mirror checks + one Local E2E inventory + three native scopes.
    assert payload["finding_count"] == len(findings) == 8
    assert payload["evidence_count"] == len(evidence) == 8 + len(SecurityControl)
    check_ids = [item["check_id"] for item in findings]
    assert len(check_ids) == len(set(check_ids))
    assert "local-e2e-inventory" in check_ids
    assert {"hardware-dense_retrieval", "hardware-stt_accuracy"} <= set(check_ids)
    evidence_ids = [item["evidence_id"] for item in evidence]
    assert len(evidence_ids) == len(set(evidence_ids)), "evidence identifiers must be unique"
    for finding in findings:
        assert len(finding["evidence_refs"]) == 1, finding["check_id"]
        assert finding["evidence_refs"][0] in set(evidence_ids)
    assert payload["assessment_environment"] == "Windows 10; baseline fixture-commit"
    assert all(item["assessment_environment"] == payload["assessment_environment"] for item in evidence)


def test_every_cited_evidence_carries_exactly_one_rerun_form(tmp_path: Path) -> None:
    """Regression: a rerun with both forms, or with an empty one, is not reproducible."""
    mirror = _mirror_payload(
        checks=(
            _check("python-lint", "blocked", blockers=("blocked",), discovered=("uv", "run", "ruff")),
            _check("frontend-build", "not implemented", exit_code=None),
            _check("python-types", "failed", executed=("uv", "run", "mypy"), exit_code=1),
        )
    )
    native = _native_payload(
        scopes=(
            _scope("tray_behavior", AssessmentStatus.ENVIRONMENT_BLOCKED, blockers=("no tray",), procedure=()),
            _scope("fallback_retrieval", AssessmentStatus.VERIFIED_WORKING, result={"matched": 1}),
        )
    )
    root = _output_root(tmp_path, mirror=mirror, native=native)

    execute_normalization(root)

    records = _normalized(root)["evidence"]
    assert len(records) == 3 + 1 + 2 + len(SecurityControl)
    for record in records:
        rerun = record["rerun"]
        argv = rerun["exact_argv"]
        procedure = rerun["numbered_procedure"]
        assert (argv is None) != (procedure is None), record["evidence_id"]
        assert argv is None or argv["values"], record["evidence_id"]
        assert procedure is None or procedure, record["evidence_id"]
        assert rerun["expected_observable"], record["evidence_id"]
    by_id = {record["evidence_id"]: record["rerun"] for record in records}
    # A discovered-but-never-executed command is still the exact rerun command.
    assert by_id["ev-mirror-python-lint"]["exact_argv"]["values"] == ["uv", "run", "ruff"]
    assert by_id["ev-mirror-python-types"]["exact_argv"]["values"] == ["uv", "run", "mypy"]
    # No command at all falls back to a non-empty numbered procedure, never an empty one.
    assert by_id["ev-mirror-frontend-build"]["exact_argv"] is None
    assert len(by_id["ev-mirror-frontend-build"]["numbered_procedure"]) >= 2
    assert by_id["ev-hardware-tray_behavior"]["numbered_procedure"], "empty procedure must fall back"


def test_blocked_maps_to_environment_blocked_and_missing_command_to_not_implemented(
    tmp_path: Path,
) -> None:
    blocker = "command cannot emit the required empirical containment proof"
    payload = _mirror_payload(
        checks=(
            _check("python-lint", "blocked", blockers=(blocker,), discovered=("uv", "run", "ruff")),
            _check("packaging-installer", "not implemented", exit_code=None),
            _check("rust-tests", "timed out", executed=("cargo", "test"), exit_code=None),
            _check("desktop-build", "no such disposition", executed=("npm", "run", "build")),
        )
    )

    findings, evidence = normalize_mirror_execution(payload, ENVIRONMENT)

    statuses = {finding.check_id: finding.status for finding in findings}
    assert statuses["python-lint"] is AssessmentStatus.ENVIRONMENT_BLOCKED
    assert statuses["packaging-installer"] is AssessmentStatus.NOT_IMPLEMENTED
    assert statuses["rust-tests"] is AssessmentStatus.FRESH_FAILURE
    # An unrecognised disposition must fail closed, never become a pass.
    assert statuses["desktop-build"] is AssessmentStatus.UNVERIFIED
    for check_id in ("python-lint", "packaging-installer"):
        assert statuses[check_id] not in _FAILURE_STATUSES
    by_check = {finding.check_id: finding for finding in findings}
    assert blocker in by_check["python-lint"].conclusion
    assert "exit code" not in by_check["python-lint"].conclusion
    assert "no command" in by_check["packaging-installer"].conclusion
    by_evidence = {item.evidence_id: item for item in evidence}
    blocked = by_evidence["ev-mirror-python-lint"]
    assert blocked.unavailable_prerequisite == blocker
    assert blocked.detection_evidence == blocker
    assert blocked.rerun.prerequisites == (blocker,)
    unimplemented = by_evidence["ev-mirror-packaging-installer"]
    assert unimplemented.primary_status is AssessmentStatus.NOT_IMPLEMENTED
    assert unimplemented.unavailable_prerequisite is None
    assert unimplemented.detection_evidence is None


def test_local_e2e_stays_blocked_and_records_its_preflight_blockers() -> None:
    findings, evidence = normalize_local_e2e(_e2e_payload(), ENVIRONMENT)

    (finding,) = findings
    (record,) = evidence
    assert finding.status is AssessmentStatus.ENVIRONMENT_BLOCKED
    assert finding.status not in _FAILURE_STATUSES
    assert "26" in finding.conclusion and "zero product failures" in finding.conclusion
    assert finding.evidence_refs == (record.evidence_id,)
    assert record.rerun.prerequisites == (
        "production index must exist",
        "no installed browser binary",
    )
    assert record.unavailable_prerequisite == "production index must exist"
    assert record.rerun.exact_argv is None and record.rerun.numbered_procedure


def test_native_blocked_scope_never_claims_a_result_and_keeps_its_blocker() -> None:
    payload = _native_payload()

    findings, evidence = normalize_native_integration(payload, ENVIRONMENT)

    by_scope = {finding.scope: finding for finding in findings}
    dense = by_scope["dense_retrieval"]
    assert dense.status is AssessmentStatus.ENVIRONMENT_BLOCKED
    assert dense.status not in _FAILURE_STATUSES
    assert "blocked before any scoped behavior" in dense.conclusion
    assert "executed once" not in dense.conclusion
    assert by_scope["fallback_retrieval"].status is AssessmentStatus.VERIFIED_WORKING
    assert "executed once within bounds" in by_scope["fallback_retrieval"].conclusion
    by_evidence = {item.evidence_id: item for item in evidence}
    # The named prerequisite itself, not the composite blocker sentence: the evidence
    # index must read as a prerequisite list rather than repeat its own label back.
    dense_evidence = by_evidence["ev-hardware-dense_retrieval"]
    assert dense_evidence.unavailable_prerequisite == "dense embedding weights"
    assert dense_evidence.unavailable_prerequisite in dense_evidence.rerun.prerequisites
    assert "unavailable prerequisite:" not in dense_evidence.unavailable_prerequisite
    assert by_evidence["ev-hardware-fallback_retrieval"].unavailable_prerequisite is None


def test_security_evidence_is_one_unverified_reproducible_record_per_control() -> None:
    records = build_security_evidence(ENVIRONMENT)

    assert len(records) == len(SecurityControl)
    assert len({item.evidence_id for item in records}) == len(SecurityControl)
    for record in records:
        assert record.primary_status is AssessmentStatus.UNVERIFIED
        assert record.primary_status not in _FAILURE_STATUSES
        assert record.rerun.exact_argv is None
        assert record.rerun.numbered_procedure
        assert record.assessment_environment == ENVIRONMENT


def test_parity_writes_every_canonical_row_once_with_an_unverified_basis(tmp_path: Path) -> None:
    root = tmp_path / "output"
    root.mkdir()

    result = execute_parity(root)

    assert result.gate is GateStatus.GREEN
    assert [item.check_id for item in result.checks] == list(PARITY_CHECK_IDS)
    payload = json.loads((root / "parity-matrix.json").read_text(encoding="utf-8"))
    rows = payload["rows"]
    assert payload["row_count"] == len(rows) == 29
    row_ids = [row["row_id"] for row in rows]
    assert len(row_ids) == len(set(row_ids)), "every parity row must appear exactly once"
    assert payload["benchmark_basis"] == "unverified"
    assert "unverified" in payload["benchmark_basis_reason"]
    for row in rows:
        assert row["benchmark_basis_status"] == AssessmentStatus.UNVERIFIED.value
        assert row["benchmark_source"] is None
        assert row["primary_status"] != AssessmentStatus.VERIFIED_WORKING.value


def test_claim_search_terms_are_deterministic_and_drop_stopwords() -> None:
    text = "Transcription happens without their cloud"
    assert claim_search_terms(text) == ("Transcription", "happens")
    assert claim_search_terms(text) == claim_search_terms(text)
    # Word order must not change the selected terms.
    assert claim_search_terms("happens Transcription cloud their without") == (
        "Transcription",
        "happens",
    )
    # Capitalised stopwords are dropped too, and at most two terms are returned.
    assert claim_search_terms("Without these transcripts always remaining offline") == (
        "transcripts",
        "remaining",
    )
    assert len(claim_search_terms("alphabet bicycles carousel dromedary")) == 2
    # A claim with no distinctive token yields nothing rather than a junk search.
    assert claim_search_terms("Because these should always work with their other") == ()
    assert claim_search_terms("") == ()
    assert claim_search_terms("all data is safe") == ()


def _tiers(reconciliation: object) -> set[EvidenceTier]:
    return {source.tier for source in reconciliation.sources}  # type: ignore[attr-defined]


def test_metric_reconciliation_adds_a_fresh_tier_only_when_a_value_was_measured() -> None:
    unmeasured = build_metric_reconciliations(
        {
            "tests": {"passed": 2198, "failed": 0},
            "line_coverage_percent": None,
            "branch_coverage_percent": None,
        }
    )

    tests, line, branch = unmeasured
    assert [item.committed_value for item in unmeasured] == [
        "1,358 tests",
        "86.7 percent",
        "78.2 percent",
    ]
    assert EvidenceTier.FRESH in _tiers(tests)
    assert any(source.value == "2,198 tests" for source in tests.sources)
    for coverage in (line, branch):
        assert _tiers(coverage) == {EvidenceTier.DOCUMENTARY, EvidenceTier.CONFIGURATION}
        assert coverage.decision.selected.tier is not EvidenceTier.FRESH
        assert "percent" in coverage.decision.selected.value

    measured = build_metric_reconciliations(
        {
            "tests": None,
            "line_coverage_percent": "91.2",
            "branch_coverage_percent": "",
        }
    )
    fresh_tests, fresh_line, fresh_branch = measured
    # No fresh test result at all means no fresh tier may be asserted.
    assert EvidenceTier.FRESH not in _tiers(fresh_tests)
    fresh_line_sources = [s for s in fresh_line.sources if s.tier is EvidenceTier.FRESH]
    assert [s.value for s in fresh_line_sources] == ["91.2 percent"]
    assert fresh_line_sources[0].source == "ev-mirror-python-coverage"
    # An empty measurement string is not a measurement.
    assert EvidenceTier.FRESH not in _tiers(fresh_branch)


def test_dense_and_stt_never_invent_a_word_error_rate_or_a_dense_result() -> None:
    dense, stt = build_dense_and_stt(_native_payload(), "ev-hardware-dense_retrieval")

    assert stt.word_error_rate_percent is None
    assert (
        stt.corpus_item_count,
        stt.total_audio_duration_seconds,
        stt.language,
        stt.local_model,
        stt.hardware,
    ) == (None, None, None, None, None)
    assert stt.primary_status is AssessmentStatus.ENVIRONMENT_BLOCKED
    # Only genuinely unavailable prerequisites are reported as blockers.
    assert stt.blockers == ("labelled speech corpus", "speech model weights")
    assert stt.evidence_reference == "ev-hardware-stt_accuracy"

    assert dense.dense_available is False
    assert dense.status is AssessmentStatus.ENVIRONMENT_BLOCKED
    assert dense.evidence_ref == "ev-hardware-dense_retrieval"
    assert "dense tier was blocked" in dense.note
    assert "freshly verified working" in dense.note
    assert "fallback tier is reported separately" in dense.note


def test_dense_stays_blocked_when_the_fallback_tier_was_not_verified() -> None:
    native = _native_payload(
        scopes=(
            _scope("dense_retrieval", AssessmentStatus.ENVIRONMENT_BLOCKED, blockers=("no weights",)),
            _scope("fallback_retrieval", AssessmentStatus.UNVERIFIED),
            _scope(
                "stt_accuracy",
                AssessmentStatus.ENVIRONMENT_BLOCKED,
                unavailable=("labelled speech corpus",),
                available=("synthetic audio fixture",),
            ),
        )
    )

    dense, stt = build_dense_and_stt(native, "ev-hardware-dense_retrieval")

    assert dense.dense_available is False
    assert dense.status is AssessmentStatus.ENVIRONMENT_BLOCKED
    assert "was not verified in this run" in dense.note
    assert "freshly verified working" not in dense.note
    assert stt.word_error_rate_percent is None
    assert stt.blockers == ("labelled speech corpus",)


def test_object_and_array_artifacts_are_loaded_by_distinct_strict_loaders(
    tmp_path: Path,
) -> None:
    """Regression: claims.json is a JSON array, every other artifact is an object.

    A single permissive loader let an array reach object-only code and only failed at
    the very end of a full run. Each loader now refuses the shape it does not own.
    """
    from assessor.report_evidence_normalization import load_artifact, load_artifact_list

    (tmp_path / "object.json").write_text('{"a": 1}', encoding="utf-8")
    (tmp_path / "array.json").write_text('[{"a": 1}, "skipped", {"b": 2}]', encoding="utf-8")

    assert load_artifact(tmp_path, "object.json") == {"a": 1}
    assert load_artifact_list(tmp_path, "array.json") == [{"a": 1}, {"b": 2}]

    with pytest.raises(ValueError, match="not a JSON object"):
        load_artifact(tmp_path, "array.json")
    with pytest.raises(ValueError, match="not a JSON array"):
        load_artifact_list(tmp_path, "object.json")
