"""Typed contracts and orchestration for the Repository State Assessor.

The package exposes immutable evidence models, fail-closed stage gates, append-only
recovery state, contained execution, parity construction, and report admission.
"""

from .artifact_schemas import EVIDENCE_COLLECTION_SCHEMA, EVIDENCE_RECORD_SCHEMA
from .assessment_paths import (
    ArtifactDestination,
    ArtifactPathError,
    ArtifactPersistenceError,
    AssessmentRunPaths,
)
from .assessment_phase_gates import (
    AssessmentPhase,
    CheckCompletion,
    ExecutionAdmission,
    GateStatus,
    PhaseExecutionResult,
    parse_phase,
)
from .assessment_pipeline import AssessmentPipeline
from .assessment_pipeline_models import (
    PhaseAction,
    PhaseExecutionContext,
    PipelineCancellation,
    PipelineOptions,
    PipelineResult,
)
from .run_manifest_append_store import (
    AppendOnlyRunManifest,
    CheckState,
    ManifestCorruption,
    ManifestEvent,
    ManifestRecord,
    ReconstructedRunState,
    RunIdentity,
)
from .baseline_collector import (
    BaselineCollectionError,
    BaselineCollector,
    CollectedBaseline,
    ToolProbe,
)
from .baseline_models import (
    AssessmentBaseline,
    FileManifest,
    HardwareInventory,
    ManifestEntry,
    OperatingSystemInventory,
    RepositoryHead,
    RepositoryHeadKind,
    ToolVersion,
    WorkspaceChange,
)
from .build_aggregation import (
    AggregateBuildResult,
    BuildComponentResult,
    aggregate_product_build,
)
from .claim_models import (
    ClaimClassificationDecision,
    ClaimClassificationFacts,
    ClaimTrace,
    DocumentaryClaim,
    DocumentaryClassification,
    HistoricalEvidenceCitation,
    PathSearchEvidence,
    classify_claim,
)
from .evidence_models import (
    AssessmentEnvironment,
    EvidenceArtifact,
    EvidenceRecord,
    RerunInstruction,
    TestCounts,
)
from .evidence_precedence import (
    EvidenceConflict,
    EvidenceDecision,
    EvidenceSource,
    EvidenceTier,
    select_evidence,
)
from .committed_metric_reconciliation import reconcile_committed_metrics
from .e2e_partition import (
    E2EDisposition,
    E2EPartition,
    E2EScenario,
    E2EScenarioDecision,
    LocalPrerequisite,
    partition_e2e_scenarios,
)
from .execution_models import (
    Applicability,
    CheckPlan,
    CommandSource,
    Prerequisite,
    RawExecutionResult,
    Termination,
    TerminationKind,
)
from .hardware_status import HardwareScope
from .model_types import (
    AssessmentStatus,
    ExactArgumentVector,
    Measurement,
    MeasurementUnit,
    NetworkMode,
    NetworkPolicy,
    OwnedProcess,
    ProcessOwnership,
    SourceLocation,
    VerificationPlane,
    WritePolicy,
    ZonedTimestamp,
)
from .native_check_plans import (
    BoundedObservable,
    NativeCheckPlan,
    NativeInputKind,
    NativeSafetyPolicy,
    build_native_check_plans,
)
from .native_preflight import (
    NativePreflightObservation,
    NativePreflightResult,
    preflight_native_check,
)
from .canonical_matrix_construction import (
    ScopedBenchmarkSource,
    ScopedParityEvidence,
    construct_canonical_parity_matrix,
)
from .parity_matrix import (
    GRANOLA_CAPABILITIES,
    WISPR_FLOW_CAPABILITIES,
    BenchmarkSource,
    BenchmarkSourceDecision,
    ParityBehaviorEvidence,
    ParityConclusionDecision,
    apply_benchmark_source_decision,
    build_canonical_parity_matrix,
    derive_evidence_parity,
    select_benchmark_source,
)
from .report_models import (
    BenchmarkSet,
    DenseRetrievalReportEntry,
    EfficacySection,
    FindingCategory,
    NextActionDisposition,
    ParityMeasurement,
    ParityRow,
    RankedFinding,
    VerificationFinding,
)
from .report_admission import admit_assessment_report
from .report_markdown_rendering import render_assessment_report_markdown
from .report_synthesis import synthesize_assessment_report
from .report_traceability import (
    ActionableConclusions,
    CitedEvidence,
    FindingCandidate,
    ReportConclusion,
    SourceReference,
    synthesize_actionable_conclusions,
)
from .run_models import (
    FileDifference,
    PhaseState,
    RunManifest,
    RunPhase,
    RunPhaseRecord,
    WorkspaceComparison,
)
from .security_control_assessment import (
    SECURITY_CONTROL_INVENTORY,
    CredentialFreeProbeEnvironment,
    SecurityAssessment,
    SecurityAssessmentContext,
    SecurityControlAssessment,
    SecurityControlDefinition,
    SecurityProbeMode,
    SecurityProbeResult,
    assess_security_controls,
    build_credential_free_probe_environment,
)
from .security_records import (
    RawSecurityArtifact,
    SanitizedSecurityArtifact,
    SecurityControl,
    SecurityControlResult,
    SecurityRecord,
    SecurityRecordCollection,
    SensitiveCategory,
    SensitiveMarker,
    VerificationMethods,
    normalize_security_records,
)
from .summary_parser import (
    CoverageTargetDecision,
    ParsedTestSummary,
    evaluate_python_coverage,
    parse_test_summary,
)
from .status_accounting import (
    ClassifiedRow,
    ClassifiedRowKind,
    StatusSummary,
    StatusTotal,
    row_id_checksum,
    summarize_classified_rows,
)
from .status_decision import (
    StatusDecision,
    StatusDecisionFacts,
    decide_status,
    is_product_failure,
)
from .stt_accuracy import (
    STTAccuracyContext,
    STTAccuracyReportEntry,
    synthesize_stt_accuracy,
)
from .structured_artifact_store import StructuredArtifactStore
from .structured_artifact_validation import ArtifactSchemaError, StructuredArtifactValidator
from .mirror_workspace import create_verified_mirror
from .source_comparison import compare_workspace_manifests
from .write_admission import evaluate_write_admission

__all__ = """
AppendOnlyRunManifest AssessmentPhase AssessmentPipeline CheckCompletion CheckState ExecutionAdmission GateStatus
ManifestCorruption ManifestEvent ManifestRecord PhaseAction PhaseExecutionContext PhaseExecutionResult
PipelineCancellation PipelineOptions PipelineResult ReconstructedRunState RunIdentity parse_phase
ActionableConclusions compare_workspace_manifests create_verified_mirror evaluate_write_admission
BoundedObservable HardwareScope NativeCheckPlan NativeInputKind NativePreflightObservation
NativePreflightResult NativeSafetyPolicy build_native_check_plans preflight_native_check
AggregateBuildResult Applicability ArtifactDestination ArtifactPathError ArtifactPersistenceError
ArtifactSchemaError AssessmentBaseline AssessmentEnvironment AssessmentRunPaths AssessmentStatus
BaselineCollectionError BaselineCollector BenchmarkSet BenchmarkSource BenchmarkSourceDecision
BuildComponentResult CheckPlan CitedEvidence ClassifiedRow ClassifiedRowKind CollectedBaseline
ClaimClassificationDecision ClaimClassificationFacts ClaimTrace CommandSource CoverageTargetDecision
CredentialFreeProbeEnvironment DocumentaryClaim DocumentaryClassification E2EDisposition E2EPartition
E2EScenario E2EScenarioDecision EVIDENCE_COLLECTION_SCHEMA EVIDENCE_RECORD_SCHEMA EvidenceArtifact
EvidenceConflict EvidenceDecision EvidenceRecord EvidenceSource EvidenceTier ExactArgumentVector
FileDifference FileManifest FindingCandidate FindingCategory GRANOLA_CAPABILITIES HardwareInventory
HistoricalEvidenceCitation LocalPrerequisite ManifestEntry Measurement MeasurementUnit NetworkMode
NetworkPolicy NextActionDisposition OperatingSystemInventory OwnedProcess ParityBehaviorEvidence
ParityConclusionDecision ParityMeasurement ParityRow ParsedTestSummary PathSearchEvidence PhaseState
Prerequisite ProcessOwnership RankedFinding RawExecutionResult RawSecurityArtifact ReportConclusion
ScopedBenchmarkSource ScopedParityEvidence RepositoryHead RepositoryHeadKind RerunInstruction RunManifest
RunPhase RunPhaseRecord STTAccuracyContext STTAccuracyReportEntry SECURITY_CONTROL_INVENTORY
SanitizedSecurityArtifact SecurityAssessment SecurityAssessmentContext SecurityControl
SecurityControlAssessment SecurityControlDefinition SecurityControlResult SecurityProbeMode
SecurityProbeResult SecurityRecord SecurityRecordCollection SensitiveCategory SensitiveMarker
SourceLocation SourceReference StatusDecision StatusDecisionFacts StatusSummary StatusTotal
StructuredArtifactStore StructuredArtifactValidator Termination TerminationKind TestCounts ToolProbe
ToolVersion VerificationMethods VerificationPlane WISPR_FLOW_CAPABILITIES WorkspaceChange
WorkspaceComparison WritePolicy ZonedTimestamp aggregate_product_build apply_benchmark_source_decision
assess_security_controls build_canonical_parity_matrix build_credential_free_probe_environment
classify_claim construct_canonical_parity_matrix derive_evidence_parity decide_status
 evaluate_python_coverage is_product_failure normalize_security_records parse_test_summary
partition_e2e_scenarios row_id_checksum select_benchmark_source select_evidence
summarize_classified_rows synthesize_actionable_conclusions synthesize_stt_accuracy
DenseRetrievalReportEntry EfficacySection VerificationFinding reconcile_committed_metrics
synthesize_assessment_report admit_assessment_report render_assessment_report_markdown
""".split()
