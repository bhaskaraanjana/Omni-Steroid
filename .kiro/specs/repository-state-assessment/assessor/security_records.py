"""Pure normalization for complete, sanitized security-control records."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SecurityControl(StrEnum):
    """The complete Requirement 7.3 security and privacy control inventory."""

    LOCAL_ONLY_STORAGE = "local_only_storage"
    ZERO_TELEMETRY = "zero_telemetry"
    KEY_CUSTODY = "key_custody"
    KILL_SWITCH = "kill_switch"
    APPROVAL_BEFORE_EXECUTE = "approval_before_execute"
    GMAIL_DRAFT_ONLY = "gmail_draft_only"
    APPEND_ONLY_AUDIT = "append_only_audit"
    MANAGED_VAULT_BOUNDARIES = "managed_vault_boundaries"


class SensitiveCategory(StrEnum):
    """Sensitive categories replaced by non-sensitive labels."""

    SECRET = "secret"
    CREDENTIAL = "credential"
    PRIVATE_AUDIO = "private_audio"
    PRIVATE_TRANSCRIPT = "private_transcript"
    PRIVATE_PATH = "private_path"
    PRIVATE_CONTENT = "private_content"

    @property
    def label(self) -> str:
        return f"[REDACTED:{self.value}]"


@dataclass(frozen=True, slots=True)
class VerificationMethods:
    """Total yes/no verification-method values required for every control."""

    hermetic: bool
    mocked: bool
    local_loopback: bool
    hardware_backed: bool
    static_only: bool

    def __post_init__(self) -> None:
        if any(type(value) is not bool for value in self.values()):
            raise TypeError("every verification method must be boolean")

    def values(self) -> tuple[bool, ...]:
        return (
            self.hermetic,
            self.mocked,
            self.local_loopback,
            self.hardware_backed,
            self.static_only,
        )


@dataclass(frozen=True, slots=True)
class SensitiveMarker:
    """One exact sensitive value and the category label replacing it."""

    category: SensitiveCategory
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.category, SensitiveCategory):
            raise TypeError("sensitive marker category must be typed")
        if not self.value:
            raise ValueError("sensitive marker value must not be empty")


@dataclass(frozen=True, slots=True)
class RawSecurityArtifact:
    """A candidate artifact that may or may not permit textual redaction."""

    artifact_id: str
    content: str
    redactable: bool


@dataclass(frozen=True, slots=True)
class SanitizedSecurityArtifact:
    """An artifact safe for permanent assessment output."""

    artifact_id: str
    content: str


@dataclass(frozen=True, slots=True)
class SecurityControlResult:
    """Raw, temporary result for one required control."""

    control: SecurityControl
    methods: VerificationMethods
    relevant_output: tuple[str, ...]
    artifacts: tuple[RawSecurityArtifact, ...]
    sensitive_markers: tuple[SensitiveMarker, ...]


@dataclass(frozen=True, slots=True)
class SecurityRecord:
    """One complete sanitized permanent record for one control."""

    control: SecurityControl
    methods: VerificationMethods
    relevant_output: tuple[str, ...]
    artifacts: tuple[SanitizedSecurityArtifact, ...]


@dataclass(frozen=True, slots=True)
class SecurityRecordCollection:
    """Canonical records plus identities of artifacts withheld from reporting."""

    records: tuple[SecurityRecord, ...]
    withheld_artifact_ids: tuple[str, ...]


def _marker_map(markers: tuple[SensitiveMarker, ...]) -> dict[str, SensitiveCategory]:
    result: dict[str, SensitiveCategory] = {}
    for marker in markers:
        prior = result.get(marker.value)
        if prior is not None and prior is not marker.category:
            raise ValueError("one sensitive value cannot have conflicting categories")
        result[marker.value] = marker.category
    return result


def _sanitize(text: str, markers: dict[str, SensitiveCategory]) -> str:
    sanitized = text
    for value in sorted(markers, key=len, reverse=True):
        sanitized = sanitized.replace(value, markers[value].label)
    return sanitized


def normalize_security_records(
    results: tuple[SecurityControlResult, ...],
) -> SecurityRecordCollection:
    """Return exactly one sanitized record for every required security control."""
    by_control: dict[SecurityControl, SecurityControlResult] = {}
    for result in results:
        if not isinstance(result.control, SecurityControl):
            raise TypeError("security control must be typed")
        if result.control in by_control:
            raise ValueError(f"duplicate security control result: {result.control.value}")
        by_control[result.control] = result

    missing = tuple(control.value for control in SecurityControl if control not in by_control)
    if missing:
        raise ValueError(f"missing security control results: {', '.join(missing)}")

    records: list[SecurityRecord] = []
    withheld: list[str] = []
    for control in SecurityControl:
        result = by_control[control]
        markers = _marker_map(result.sensitive_markers)
        raw_artifact_ids: set[str] = set()
        sanitized_artifact_ids: set[str] = set()
        admitted: list[SanitizedSecurityArtifact] = []
        for artifact in result.artifacts:
            if not artifact.artifact_id or artifact.artifact_id in raw_artifact_ids:  # fail-closed: raw identifiers remain non-empty and unique
                raise ValueError("artifact identifiers must be non-empty and unique per control")
            raw_artifact_ids.add(artifact.artifact_id)
            sanitized_artifact_id = _sanitize(artifact.artifact_id, markers)  # redaction: artifact identifiers never publish sensitive values
            if sanitized_artifact_id in sanitized_artifact_ids:  # fail-closed: redaction cannot collapse distinct artifact identifiers
                raise ValueError("sanitized artifact identifiers must be unique per control")
            sanitized_artifact_ids.add(sanitized_artifact_id)
            matched_categories = {  # sensitivity boundary: identifiers and content receive identical marker analysis
                category
                for value, category in markers.items()
                if value in artifact.artifact_id or value in artifact.content
            }
            unsafe = SensitiveCategory.PRIVATE_AUDIO in matched_categories or (
                bool(matched_categories) and not artifact.redactable
            )
            if unsafe:
                withheld.append(sanitized_artifact_id)  # redaction: withheld identifiers never publish sensitive values
                continue
            admitted.append(
                SanitizedSecurityArtifact(
                    sanitized_artifact_id, _sanitize(artifact.content, markers)
                )
            )
        records.append(
            SecurityRecord(
                control=control,
                methods=result.methods,
                relevant_output=tuple(
                    _sanitize(output, markers) for output in result.relevant_output
                ),
                artifacts=tuple(admitted),
            )
        )
    return SecurityRecordCollection(tuple(records), tuple(withheld))