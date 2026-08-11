"""Inventory and fail-closed normalization for hermetic security assessments.

This module never reads the parent environment or contacts providers. It admits only
static inspection or disposable, loopback-contained observations and emits one
sanitized security record plus one evidence record for every Requirement 7 control.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .evidence_models import AssessmentEnvironment, EvidenceRecord
from .external_action_refusal import ExternalActionRefusal, PendingActionState, RefusalCondition
from .model_types import ProcessOwnership, SourceLocation, ZonedTimestamp
from .security_records import (
    RawSecurityArtifact,
    SecurityControl,
    SecurityControlResult,
    SecurityRecord,
    SensitiveMarker,
    VerificationMethods,
    normalize_security_records,
)


class SecurityProbeMode(StrEnum):
    """The only assessment methods permitted for provider-adjacent controls."""

    STATIC_INSPECTION = "static_inspection"
    HERMETIC_EXECUTION = "hermetic_execution"


@dataclass(frozen=True, slots=True)
class SecurityControlDefinition:
    """One canonical, separately assessed Requirement 7.3 control."""

    control: SecurityControl
    scope: str


SECURITY_CONTROL_INVENTORY = tuple(
    SecurityControlDefinition(control, scope)
    for control, scope in (
        (SecurityControl.LOCAL_ONLY_STORAGE, "local-only storage of audio, transcripts, embeddings, notes, and keys"),
        (SecurityControl.ZERO_TELEMETRY, "zero analytics, usage, crash-report, or telemetry transmission"),
        (SecurityControl.KEY_CUSTODY, "no plaintext, log, or UI-process key disclosure"),
        (SecurityControl.KILL_SWITCH, "kill-switch blocks external calls while local behavior remains available"),
        (SecurityControl.APPROVAL_BEFORE_EXECUTE, "approval before calendar, contact, vault, and draft execution"),
        (SecurityControl.GMAIL_DRAFT_ONLY, "Gmail draft creation with no mail-send capability"),
        (SecurityControl.APPEND_ONLY_AUDIT, "audit entries permit append and reject modification or deletion"),
        (SecurityControl.MANAGED_VAULT_BOUNDARIES, "user content outside managed vault regions remains unchanged"),
    )
)

_CREDENTIAL_NAME = re.compile(r"(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTHORIZATION|OAUTH)", re.IGNORECASE)
_REFUSAL_CONTROLS = frozenset({SecurityControl.KILL_SWITCH, SecurityControl.APPROVAL_BEFORE_EXECUTE, SecurityControl.GMAIL_DRAFT_ONLY})


@dataclass(frozen=True, slots=True)
class CredentialFreeProbeEnvironment:
    """Fresh child environment values that intentionally do not inherit parent state."""

    values: tuple[tuple[str, str], ...]
    inherits_parent: bool = False


def build_credential_free_probe_environment(
    run_root: Path,
    safe_values: tuple[tuple[str, str], ...] = (),
) -> CredentialFreeProbeEnvironment:
    """Build an allowlisted environment without reading inherited credential values."""
    root = str(run_root.resolve())
    values = {
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "HOME": root,
        "USERPROFILE": root,
        "TEMP": root,
        "TMP": root,
        "OMNI_ENV_FILE": str(run_root / "absent-provider-credentials.env"),
    }
    for name, value in safe_values:
        if not name or _CREDENTIAL_NAME.search(name):
            raise ValueError(f"credential-like environment name is forbidden: {name}")
        values[name] = value
    return CredentialFreeProbeEnvironment(tuple(sorted(values.items())))


@dataclass(frozen=True, slots=True)
class SecurityProbeResult:
    """Temporary observation from static inspection or disposable execution."""

    control: SecurityControl
    mode: SecurityProbeMode
    complete_scope: bool
    relevant_output: tuple[str, ...] = ()
    source_locations: tuple[SourceLocation, ...] = ()
    artifacts: tuple[RawSecurityArtifact, ...] = ()
    sensitive_markers: tuple[SensitiveMarker, ...] = ()
    refusal: ExternalActionRefusal | None = None
    synthetic_non_private_input: bool = False
    disposable_state: bool = False
    inherited_credentials: bool = False
    network_loopback_only: bool = False
    live_provider_call_count: int = 0
    provider_payload_count: int = 0
    provider_side_effect_count: int = 0
    process_ownership: ProcessOwnership | None = None
    network_observation_ref: str | None = None
    write_audit_ref: str | None = None
    hardware_backed: bool = False
    duration_ms: int = 0
    unavailable_prerequisites: tuple[str, ...] = ()
    failure_observed: bool = False

    def __post_init__(self) -> None:
        """Reject any observation that could represent credential inheritance or egress."""
        if not isinstance(self.control, SecurityControl) or not isinstance(self.mode, SecurityProbeMode):
            raise TypeError("security probe control and mode must be typed")
        if min(self.live_provider_call_count, self.provider_payload_count, self.provider_side_effect_count, self.duration_ms) < 0:
            raise ValueError("security probe counts and duration must be non-negative")
        if self.live_provider_call_count:
            raise ValueError("live provider calls are prohibited")
        if self.provider_payload_count:
            raise ValueError("provider payload transmission is prohibited")
        if self.provider_side_effect_count:
            raise ValueError("provider side effects are prohibited")
        if self.inherited_credentials:
            raise ValueError("inherited credentials are prohibited")
        if any(not item for item in self.unavailable_prerequisites):
            raise ValueError("unavailable prerequisite names must be non-empty")
        if self.complete_scope and (self.failure_observed or self.unavailable_prerequisites):
            raise ValueError("a complete control pass cannot also fail or be blocked")
        if self.mode is SecurityProbeMode.STATIC_INSPECTION:
            if self.refusal is not None or self.process_ownership is not None:
                raise ValueError("static inspection cannot execute product code")
        elif self.complete_scope:
            self._validate_complete_hermetic_execution()
        if self.refusal is not None:
            _validate_refusal(self.refusal)

    @property
    def execution_attempted(self) -> bool:
        """Static inspection is fresh assessment execution; dynamic execution needs ownership."""
        return self.mode is SecurityProbeMode.STATIC_INSPECTION or self.process_ownership is not None

    def _validate_complete_hermetic_execution(self) -> None:
        if not self.synthetic_non_private_input or not self.disposable_state:
            raise ValueError("complete hermetic execution requires synthetic input and disposable state")
        if not self.network_loopback_only or self.network_observation_ref is None:
            raise ValueError("complete hermetic execution requires loopback-only network evidence")
        if self.process_ownership is None or not self.process_ownership.cleanup_completed:
            raise ValueError("complete hermetic execution requires cleaned assessment-owned processes")
        if self.write_audit_ref is None:
            raise ValueError("complete hermetic execution requires a disposable-state write audit")
        if self.control in _REFUSAL_CONTROLS and self.refusal is None:
            raise ValueError("external-call control requires an absent-credential or rejecting-fake refusal")


def _validate_refusal(refusal: ExternalActionRefusal) -> None:
    """Require observable, state-preserving refusal with no external effect."""
    if refusal.condition not in tuple(RefusalCondition) or not refusal.failure_indication:
        raise ValueError("refusal requires an allowed condition and observable failure")
    if refusal.non_loopback_request_count or refusal.provider_side_effect_count:
        raise ValueError("refusal reached a provider or non-loopback address")
    if refusal.state_after is PendingActionState.EXECUTED or refusal.state_after is not refusal.state_before:
        raise ValueError("refused action changed pending execution state")
    if refusal.data_hashes_after != refusal.data_hashes_before:
        raise ValueError("refused action changed pre-existing user data")
    expected_loopback = int(refusal.condition is RefusalCondition.REJECTING_LOOPBACK_FAKE)
    if refusal.loopback_fake_request_count != expected_loopback:
        raise ValueError("refusal fake request count does not match its condition")


@dataclass(frozen=True, slots=True)
class SecurityAssessmentContext:
    """Baseline and environment facts shared by all security evidence records."""

    started_at: ZonedTimestamp
    environment: AssessmentEnvironment
    source_revision: str
    cwd: str

    def __post_init__(self) -> None:
        if not self.source_revision.strip() or not self.cwd:
            raise ValueError("security assessment context requires revision and cwd")


@dataclass(frozen=True, slots=True)
class SecurityControlAssessment:
    """The sanitized control result paired with its separate evidence record."""

    record: SecurityRecord
    evidence: EvidenceRecord


@dataclass(frozen=True, slots=True)
class SecurityAssessment:
    """Complete canonical security assessment and withheld artifact identities."""

    controls: tuple[SecurityControlAssessment, ...]
    withheld_artifact_ids: tuple[str, ...]

    def by_control(self, control: SecurityControl) -> SecurityControlAssessment:
        """Return one canonical control assessment or fail for an invalid inventory."""
        for item in self.controls:
            if item.record.control is control:
                return item
        raise KeyError(control)


def assess_security_controls(
    probes: tuple[SecurityProbeResult, ...],
    context: SecurityAssessmentContext,
) -> SecurityAssessment:
    """Validate, sanitize, classify, and evidence all eight security controls."""
    from .security_evidence import build_security_evidence

    raw_results = tuple(
        SecurityControlResult(
            control=probe.control,
            methods=_methods_for(probe),
            relevant_output=probe.relevant_output,
            artifacts=probe.artifacts,
            sensitive_markers=probe.sensitive_markers,
        )
        for probe in probes
    )
    sanitized = normalize_security_records(raw_results)
    probes_by_control = {probe.control: probe for probe in probes}
    records = tuple(
        SecurityControlAssessment(
            record=record,
            evidence=build_security_evidence(probes_by_control[record.control], record, context),
        )
        for record in sanitized.records
    )
    return SecurityAssessment(records, sanitized.withheld_artifact_ids)


def _methods_for(probe: SecurityProbeResult) -> VerificationMethods:
    static = probe.mode is SecurityProbeMode.STATIC_INSPECTION
    executed = probe.execution_attempted
    mocked = bool(probe.refusal and probe.refusal.condition is RefusalCondition.REJECTING_LOOPBACK_FAKE)
    return VerificationMethods(
        hermetic=static or (executed and probe.synthetic_non_private_input and probe.disposable_state),
        mocked=mocked,
        local_loopback=static or (executed and probe.network_loopback_only),
        hardware_backed=probe.hardware_backed,
        static_only=static,
    )
