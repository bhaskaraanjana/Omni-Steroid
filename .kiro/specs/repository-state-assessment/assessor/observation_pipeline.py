"""Compose real observation and bounded mirror-execution phases."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path

from .assessment_cli import CLIRequest
from .assessment_phase_gates import (
    AssessmentPhase,
    ExecutionAdmission,
    GateStatus,
    PhaseExecutionResult,
)
from .assessment_pipeline import AssessmentPipeline
from .assessment_pipeline_models import PhaseAction
from .baseline_collector import BaselineCollector
from .baseline_models import FileManifest
from .claim_inventory import discover_primary_claim_documents, extract_material_claims
from .discovery_classification import classify_discovery_outcomes
from .discovery_models import RepositoryDiscoveryReport
from .local_e2e_phase import LOCAL_E2E_CHECK_IDS, execute_local_e2e
from .loopback_only_network_containment import LoopbackOnlyNetworkContainment
from .mirror_execution_phase import TASK_11_4_CHECK_IDS, execute_mirror_checks
from .mirror_workspace import MirrorCopyResult, create_verified_mirror
from .model_types import ZonedTimestamp
from .native_integration_phase import NATIVE_CHECK_IDS, execute_native_integration
from .network_containment_admission import probe_discovered_containment
from .observation_manifest_scoping import (
    is_assessment_output,
    without_assessment_outputs,
)
from .observation_root_validation import validate_assessment_roots
from .observation_summary_record import (
    CONTAINMENT_STOP_REASON,
    build_observation_summary,
)
from .observation_support import (
    MIRROR_EXCLUDED_PREFIXES,
    build_omissions,
    repository_search_paths,
    resolve_workspace_tools,
    write_json,
)
from .report_publication_phase import (
    NORMALIZATION_CHECK_IDS,
    PARITY_CHECK_IDS,
    REPORT_CHECK_IDS,
    execute_normalization,
    execute_parity,
    execute_report,
)
from .repository_discovery import discover_repository
from .run_manifest_append_store import AppendOnlyRunManifest
from .run_models import WorkspaceComparison
from .source_comparison import collect_git_workspace_manifest, compare_workspace_manifests


@dataclass
class _ObservationState:
    source: Path
    temporary: Path
    output: Path
    run_id: str
    source_manifest: FileManifest | None = None
    mirror: MirrorCopyResult | None = None
    claims_count: int = 0
    scenario_count: int = 0
    check_count: int = 0
    discovery_report: RepositoryDiscoveryReport | None = None
    omissions: tuple[dict[str, object], ...] = ()


def build_observation_pipeline(
    request: CLIRequest, store: AppendOnlyRunManifest) -> AssessmentPipeline:
    """Build the real observation stages; later execution stages stay unreachable."""
    if request.run_identity is None:
        raise ValueError("observation composition requires a new run identity")
    identity = request.run_identity
    state = _ObservationState(
        Path(identity.source_repository_root).resolve(strict=True),
        Path(identity.temporary_run_root).resolve(strict=True),
        Path(identity.permanent_output_root).resolve(strict=True),
        identity.run_id,
    )
    validate_assessment_roots(
        source=state.source,
        temporary=state.temporary,
        output=state.output,
        manifest_path=request.manifest_path,
    )

    def baseline(_context: object) -> PhaseExecutionResult:
        source_ref = str(state.output / "source-manifest.json")
        collected = BaselineCollector().collect(
            state.source,
            run_id=state.run_id,
            designated_roots=(str(state.temporary), str(state.output)),
            source_manifest_ref=source_ref,
        )
        source_manifest = without_assessment_outputs(collected.source_manifest)
        baseline_record = replace(
            collected.baseline,
            untracked_paths=tuple(
                path for path in collected.baseline.untracked_paths
                if not is_assessment_output(path)
            ),
            mirror_manifest_ref=str(state.output / "mirror-manifest.json"),
        )
        state.source_manifest = source_manifest
        write_json(state.output, "baseline.json", baseline_record.to_dict())
        write_json(state.output, "source-manifest.json", source_manifest.to_dict())
        mirror = create_verified_mirror(
            state.source,
            state.temporary / "mirror",
            source_manifest,
            excluded_prefixes=MIRROR_EXCLUDED_PREFIXES,
        )
        state.mirror = mirror
        write_json(state.output, "mirror-copy.json", mirror)
        write_json(state.output, "mirror-manifest.json", mirror.mirror_manifest.to_dict())
        if not mirror.verified:
            return PhaseExecutionResult(
                GateStatus.FAILED,
                (str(state.output / "mirror-copy.json"),),
                f"mirror verification failed for {len(mirror.mismatches)} file(s)",
            )
        return PhaseExecutionResult(
            GateStatus.GREEN,
            (
                str(state.output / "baseline.json"),
                str(state.output / "source-manifest.json"),
                str(state.output / "mirror-copy.json"),
                str(state.output / "mirror-manifest.json"),
            ),
            None,
        )

    def claims(_context: object) -> PhaseExecutionResult:
        mirror_root = _verified_mirror(state)
        documents = discover_primary_claim_documents(mirror_root)
        claims_found = extract_material_claims(mirror_root, documents)
        state.claims_count = len(claims_found)
        write_json(state.output, "claim-documents.json", documents)
        write_json(state.output, "claims.json", claims_found)
        return PhaseExecutionResult(
            GateStatus.GREEN,
            (str(state.output / "claim-documents.json"), str(state.output / "claims.json")),
            None,
        )

    def discovery(_context: object) -> PhaseExecutionResult:
        mirror_root = _verified_mirror(state)
        discovered = discover_repository(mirror_root, resolve_tools=False, search_complete=True)
        required_tools = tuple(
            tool
            for command in discovered.commands
            for tool in command.required_tools
        )
        resolutions = resolve_workspace_tools(state.source, required_tools)
        outcomes = classify_discovery_outcomes(
            discovered.commands,
            repository_search_paths(discovered),
            True,
            resolutions,
        )
        report = RepositoryDiscoveryReport(
            discovered.commands, discovered.scenarios, discovered.targets,
            discovered.locked_versions, resolutions, outcomes,
        )
        state.scenario_count = len(report.scenarios)
        state.check_count = len(report.outcomes)
        state.discovery_report = report
        proof_candidates, blocked_containment = probe_discovered_containment(
            LoopbackOnlyNetworkContainment(state.temporary),
            report.commands,
            mirror_root,
            state.temporary,
        )
        containment_omissions = tuple(
            {
                **asdict(item),
                "operation_id": f"network-containment:{item.operation_id}",
            }
            for item in blocked_containment
        )
        containment_admitted = bool(proof_candidates)
        state.omissions = (
            build_omissions(
                report,
                state.mirror,
                mirror_execution_admitted=containment_admitted,
            )
            + containment_omissions
        )
        admission = ExecutionAdmission(
            True, True, True, True, containment_admitted
        )
        summary = build_observation_summary(
            run_id=state.run_id,
            report=report,
            admission=admission,
            files_hashed=(
                len(state.source_manifest.entries) if state.source_manifest else 0
            ),
            claims_inventoried=state.claims_count,
            omissions=state.omissions,
            proof_candidates=tuple(proof_candidates),
            blocked_prelaunch_count=len(containment_omissions),
        )
        write_json(state.output, "discovery.json", report)
        write_json(state.output, "observation-summary.json", summary)
        gate = GateStatus.GREEN if admission.admitted else GateStatus.INCONCLUSIVE
        reason = None if admission.admitted else CONTAINMENT_STOP_REASON
        return PhaseExecutionResult(
            gate,
            (str(state.output / "discovery.json"), str(state.output / "observation-summary.json")),
            reason,
            execution_admission=admission,
        )

    def mirror_execution(_context: object) -> PhaseExecutionResult:
        if state.discovery_report is None:
            raise RuntimeError("discovery report is unavailable")
        return execute_mirror_checks(
            _verified_mirror(state), state.temporary, state.output, state.discovery_report
        )

    def local_e2e(_context: object) -> PhaseExecutionResult:
        return execute_local_e2e(
            _verified_mirror(state),
            state.temporary,
            state.output,
            ownership_token=identity.ownership_token,
        )

    def native_integration(_context: object) -> PhaseExecutionResult:
        return execute_native_integration(
            _verified_mirror(state), state.temporary, state.output
        )

    def normalization(_context: object) -> PhaseExecutionResult:
        return execute_normalization(state.output)

    def parity(_context: object) -> PhaseExecutionResult:
        return execute_parity(state.output)

    def report(_context: object) -> PhaseExecutionResult:
        return execute_report(
            _verified_mirror(state), state.source, state.output, state.run_id
        )

    actions = (
        PhaseAction(AssessmentPhase.BASELINE, (), baseline),
        PhaseAction(AssessmentPhase.CLAIMS, (), claims),
        PhaseAction(AssessmentPhase.DISCOVERY_ADMISSION, (), discovery),
        PhaseAction(
            AssessmentPhase.MIRROR_EXECUTION, TASK_11_4_CHECK_IDS, mirror_execution
        ),
        PhaseAction(AssessmentPhase.LOCAL_E2E, LOCAL_E2E_CHECK_IDS, local_e2e),
        PhaseAction(
            AssessmentPhase.NATIVE_INTEGRATION, NATIVE_CHECK_IDS, native_integration
        ),
        PhaseAction(
            AssessmentPhase.NORMALIZATION, NORMALIZATION_CHECK_IDS, normalization
        ),
        PhaseAction(AssessmentPhase.PARITY, PARITY_CHECK_IDS, parity),
        PhaseAction(AssessmentPhase.REPORT, REPORT_CHECK_IDS, report),
    )
    return AssessmentPipeline(store, actions, lambda: _compare_source(state))


def _verified_mirror(state: _ObservationState) -> Path:
    if state.mirror is None or not state.mirror.verified:
        raise RuntimeError("verified mirror is unavailable")
    return state.mirror.mirror_root


def _compare_source(state: _ObservationState) -> WorkspaceComparison:
    now = ZonedTimestamp(datetime.now().astimezone())
    final = collect_git_workspace_manifest(
        state.source, manifest_id=f"{state.run_id}-final", created_at=now
    )
    final_ref = str(state.output / "final-source-manifest.json")
    write_json(state.output, "final-source-manifest.json", final.to_dict())
    if state.source_manifest is None:
        return WorkspaceComparison("unavailable", final_ref, False, False, False, (), (), now)
    return compare_workspace_manifests(
        state.source_manifest, final,
        baseline_manifest_ref=str(state.output / "source-manifest.json"),
        final_manifest_ref=final_ref,
        designated_roots=(str(state.temporary), str(state.output)),
        observed_writes=(), compared_at=now,
    )
