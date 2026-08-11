"""Normalize published phase artifacts into findings and cited evidence.

The published artifacts are the source of truth: this stage reads them back rather
than trusting in-memory phase state. Every check becomes exactly one finding with
one primary status and one evidence record, and a blocked check keeps its complete
rerun instruction so it is reproducible rather than merely dismissed.
"""

from __future__ import annotations

import json
from pathlib import Path

from .evidence_models import RerunInstruction
from .model_types import AssessmentStatus, ExactArgumentVector, VerificationPlane
from .report_models import VerificationFinding
from .report_traceability import CitedEvidence
from .security_records import SecurityControl

_MIRROR_PLANES = {
    "python": VerificationPlane.PYTHON_ENGINE,
    "typescript": VerificationPlane.TYPESCRIPT_UI,
    "rust": VerificationPlane.RUST_TAURI_SHELL,
    "engine-build": VerificationPlane.PRODUCT_BUILD,
    "frontend-build": VerificationPlane.PRODUCT_BUILD,
    "desktop-build": VerificationPlane.PRODUCT_BUILD,
    "frozen-engine-smoke": VerificationPlane.PRODUCT_BUILD,
    "packaging": VerificationPlane.PACKAGING_RELEASE,
    "hermetic-security": VerificationPlane.SECURITY_PRIVACY,
}
_MIRROR_STATUS = {
    "passed": AssessmentStatus.VERIFIED_WORKING,
    "failed": AssessmentStatus.FRESH_FAILURE,
    "timed out": AssessmentStatus.FRESH_FAILURE,
    "blocked": AssessmentStatus.ENVIRONMENT_BLOCKED,
    "not implemented": AssessmentStatus.NOT_IMPLEMENTED,
}
# Static-only inspection is the honest method set: hermetic security execution
# remains unimplemented, so no control may claim a hermetic or mocked method.
SECURITY_EVIDENCE_IDS = {
    control: f"ev-security-{control.value}" for control in SecurityControl
}


def load_artifact(output_root: Path, name: str) -> dict[str, object]:
    """Read one published artifact back as the authoritative record."""
    value = json.loads((output_root / name).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{name} is not a JSON object")
    return value


def load_artifact_list(output_root: Path, name: str) -> list[dict[str, object]]:
    """Read a published artifact that is a JSON array rather than an object.

    `claims.json` is a bare array; keeping the two loaders distinct stops an array
    artifact from being silently accepted where an object is required, and vice versa.
    """
    value = json.loads((output_root / name).read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError(f"{name} is not a JSON array")
    return [item for item in value if isinstance(item, dict)]


def artifact_records(payload: dict[str, object], key: str) -> list[dict[str, object]]:
    """Return one artifact's record list, refusing a malformed shape outright."""
    value = payload[key]
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list of records")
    return [item for item in value if isinstance(item, dict)]


def _strings(payload: dict[str, object], key: str) -> tuple[str, ...]:
    """Return one artifact field as a string tuple, refusing a malformed shape."""
    value = payload.get(key) or ()
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{key} must be a list of strings")
    return tuple(str(item) for item in value)


def _evidence(
    evidence_id: str,
    status: AssessmentStatus,
    prerequisites: tuple[str, ...],
    argv: tuple[str, ...],
    procedure: tuple[str, ...],
    observable: str,
    environment: str,
    blockers: tuple[str, ...],
) -> CitedEvidence:
    blocked = status is AssessmentStatus.ENVIRONMENT_BLOCKED
    unavailable: str | None = None
    if blocked:
        # A blocked record must name its unavailable prerequisite, and that name must
        # appear in the rerun prerequisites so the omission is reproducible.
        unavailable = blockers[0] if blockers else (
            prerequisites[0] if prerequisites else "an unnamed prerequisite"
        )
        if unavailable not in prerequisites:
            prerequisites = (unavailable, *prerequisites)
    # A rerun carries exactly one executable form. A check with no discovered command
    # still gets a reproducible procedure rather than an empty, useless instruction.
    if argv:
        rerun = RerunInstruction(prerequisites, ExactArgumentVector(argv), None, observable)
    else:
        steps = procedure or (
            f"Resolve a current repository command for {evidence_id.removeprefix('ev-')}",
            "Execute it once inside the verified mirror under full containment",
        )
        rerun = RerunInstruction(prerequisites, None, steps, observable)
    return CitedEvidence(
        evidence_id,
        status,
        rerun,
        environment,
        unavailable,
        # A blocked check still records how the blocker was detected, so a reader can
        # reproduce the preflight rather than take the omission on trust.
        unavailable,
    )


def _mirror_plane(check_id: str) -> VerificationPlane:
    for prefix, plane in _MIRROR_PLANES.items():
        if check_id.startswith(prefix):
            return plane
    return VerificationPlane.PRODUCT_BUILD


def normalize_mirror_execution(
    payload: dict[str, object], environment: str
) -> tuple[tuple[VerificationFinding, ...], tuple[CitedEvidence, ...]]:
    """Turn each Task 11.4 check into one finding and one evidence record."""
    findings: list[VerificationFinding] = []
    evidence: list[CitedEvidence] = []
    for record in artifact_records(payload, "checks"):
        check_id = str(record["check_id"])
        status = _MIRROR_STATUS.get(str(record["status"]), AssessmentStatus.UNVERIFIED)
        evidence_id = f"ev-mirror-{check_id}"
        blockers = _strings(record, "blockers")
        argv = _strings(record, "executed_argv") or _strings(record, "discovered_argv")
        findings.append(
            VerificationFinding(
                check_id,
                _mirror_plane(check_id),
                check_id,
                status,
                _mirror_conclusion(check_id, record, status, blockers),
                (evidence_id,),
            )
        )
        evidence.append(
            _evidence(
                evidence_id,
                status,
                tuple(blockers),
                argv,
                (),
                "one terminating result with captured output and counts",
                environment,
                blockers,
            )
        )
    return tuple(findings), tuple(evidence)


def _mirror_conclusion(
    check_id: str,
    record: dict[str, object],
    status: AssessmentStatus,
    blockers: tuple[str, ...],
) -> str:
    if status is AssessmentStatus.ENVIRONMENT_BLOCKED:
        return f"{check_id} was omitted before launch: {blockers[0] if blockers else 'blocked'}"
    if status is AssessmentStatus.NOT_IMPLEMENTED:
        return f"{check_id} has no command in the current repository configuration"
    counts = record.get("test_counts") or {}
    return (
        f"{check_id} terminated with exit code {record['exit_code']} "
        f"and recorded counts {counts}"
    )


def normalize_local_e2e(
    payload: dict[str, object], environment: str
) -> tuple[tuple[VerificationFinding, ...], tuple[CitedEvidence, ...]]:
    """Report the Local E2E inventory as one blocked, fully reproducible check."""
    counts = payload["disposition_counts"]
    blocked = tuple(
        str(item["reason"])
        for item in artifact_records(payload, "preflights")
        if item["status"] == "blocked"
    )
    evidence_id = "ev-local-e2e-inventory"
    finding = VerificationFinding(
        "local-e2e-inventory",
        VerificationPlane.LOCAL_E2E,
        "configured Playwright scenarios",
        AssessmentStatus.ENVIRONMENT_BLOCKED,
        (
            f"every one of {payload['scenario_count']} scenarios received exactly one "
            f"disposition {counts}; zero scenarios executed and zero product failures "
            "were recorded"
        ),
        (evidence_id,),
    )
    evidence_record = _evidence(
        evidence_id,
        AssessmentStatus.ENVIRONMENT_BLOCKED,
        blocked,
        (),
        ("Complete every Local E2E preflight before launching any process",),
        "one disposition per scenario with no process started",
        environment,
        blocked,
    )
    return (finding,), (evidence_record,)


def normalize_native_integration(
    payload: dict[str, object], environment: str
) -> tuple[tuple[VerificationFinding, ...], tuple[CitedEvidence, ...]]:
    """Turn each hardware/native scope into one finding and one evidence record."""
    findings: list[VerificationFinding] = []
    evidence: list[CitedEvidence] = []
    for record in artifact_records(payload, "scopes"):
        scope = str(record["scope"])
        status = AssessmentStatus(str(record["status"]))
        evidence_id = f"ev-hardware-{scope}"
        prerequisites = tuple(
            str(item["prerequisite"])
            for item in artifact_records(record, "preflight")
        )
        # Name the unavailable prerequisites themselves rather than the composite
        # blocker sentence, so the evidence index reads as a prerequisite list and
        # does not repeat "unavailable prerequisite:" back to the reader.
        unavailable = tuple(
            str(item["prerequisite"])
            for item in artifact_records(record, "preflight")
            if item["available"] is False
        )
        blockers = unavailable or _strings(record, "blockers")
        findings.append(
            VerificationFinding(
                str(record["check_id"]),
                VerificationPlane.HARDWARE_INTEGRATION,
                scope,
                status,
                _native_conclusion(scope, record, status, blockers),
                (evidence_id,),
            )
        )
        evidence.append(
            _evidence(
                evidence_id,
                status,
                prerequisites,
                (),
                _strings(record, "numbered_procedure"),
                "; ".join(
                    str(item["name"])
                    for item in artifact_records(record, "observables")
                ),
                environment,
                blockers,
            )
        )
    return tuple(findings), tuple(evidence)


def _native_conclusion(
    scope: str,
    record: dict[str, object],
    status: AssessmentStatus,
    blockers: tuple[str, ...],
) -> str:
    if status is AssessmentStatus.ENVIRONMENT_BLOCKED:
        return (
            f"{scope} was blocked before any scoped behavior: "
            f"{blockers[0] if blockers else 'prerequisite unavailable'}"
        )
    result = record.get("result")
    if status is AssessmentStatus.VERIFIED_WORKING and isinstance(result, dict):
        observed = json.dumps(result, sort_keys=True)
        return f"{scope} executed once within bounds and observed {observed}"
    return f"{scope} did not reach a verified outcome; status {status.value}"


def security_records_are_static_only() -> tuple[str, ...]:
    """Return the honest per-control note for an unimplemented hermetic plane."""
    return (
        "assessed by static inspection only",
        "hermetic security execution is not implemented, so no dynamic method was used",
    )
