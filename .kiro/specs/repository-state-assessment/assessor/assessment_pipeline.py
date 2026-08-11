"""Orchestrate existing assessment stages through durable hard phase gates.

The pipeline owns ordering, resume, cancellation recovery, owned-process cleanup, and
mandatory final comparison. Stage actions remain thin adapters over existing collectors,
runners, normalizers, parity construction, and report synthesis/admission components.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from .assessment_partial_report import render_partial_assessment_report
from .assessment_phase_gates import (
    AssessmentPhase,
    GateStatus,
    predecessor_phases,
)
from .assessment_pipeline_models import (
    CleanupExecutor,
    PhaseAction,
    PhaseExecutionContext,
    PipelineCancellation,
    PipelineOptions,
    PipelineResult,
)
from .owned_process_tree import cleanup_owned_processes
from .preservation import AssessmentTermination
from .process_cleanup import CleanupMode
from .run_manifest_append_store import (
    AppendOnlyRunManifest,
    CheckState,
    ReconstructedRunState,
)
from .run_models import PhaseState, WorkspaceComparison
from .source_comparison import FinalComparisonGuard, FinalComparisonRecord


class AssessmentPipeline:
    """Run or resume all seven stages, advancing only through green gates."""

    def __init__(
        self,
        manifest: AppendOnlyRunManifest,
        actions: tuple[PhaseAction, ...],
        compare_source: Callable[[], WorkspaceComparison],
        *,
        cleanup: CleanupExecutor = cleanup_owned_processes,
        cancellation: PipelineCancellation | None = None,
    ) -> None:
        expected = tuple(AssessmentPhase)
        if tuple(action.phase for action in actions) != expected:
            raise ValueError("phase actions must contain every phase in exact order")
        self._manifest = manifest
        self._actions = actions
        self._compare_source = compare_source
        self._cleanup = cleanup
        self._cancellation = cancellation or PipelineCancellation()

    def run(self, options: PipelineOptions | None = None) -> PipelineResult:
        """Execute admissible phases and always finish with source comparison."""
        selected_options = options or PipelineOptions()
        partial = False
        reason = "assessment completed"
        termination = AssessmentTermination.SUCCESS
        active_phase: AssessmentPhase | None = None
        comparison_preserved = False
        cleanup_performed = False

        stale_reason = self._recover_stale_attempts()
        if stale_reason is not None:
            partial, reason, termination = True, stale_reason, AssessmentTermination.ABORT

        def write_comparison(record: FinalComparisonRecord) -> object:
            comparison = record.comparison
            refs = (comparison.baseline_manifest_ref, comparison.final_manifest_ref)
            return self._manifest.append_final_comparison(
                comparison.preservation_confirmed,
                refs,
                f"{record.termination.value} termination source comparison",
            )

        guard = FinalComparisonGuard(self._compare_source, write_comparison)
        try:
            if not partial:
                for action in self._actions:
                    active_phase = action.phase
                    state = self._manifest.state()
                    ordering_error = self._ordering_error(state, action.phase)
                    if ordering_error is not None:
                        partial, reason, termination = (
                            True,
                            ordering_error,
                            AssessmentTermination.FAILURE,
                        )
                        break
                    if state.gate_for(action.phase) is GateStatus.GREEN:
                        continue
                    if tuple(AssessmentPhase).index(action.phase) > tuple(AssessmentPhase).index(
                        selected_options.effective_limit
                    ):
                        partial, reason = (
                            True,
                            f"stopped after {selected_options.effective_limit.value}",
                        )
                        break
                    if self._cancellation.requested:
                        partial, reason, termination = (
                            True,
                            "explicit cancellation requested",
                            AssessmentTermination.ABORT,
                        )
                        break
                    self._execute_phase(action)
                    gate = self._manifest.state().gate_for(action.phase)
                    if gate is not GateStatus.GREEN:
                        record = self._manifest.state().gate_record(action.phase)
                        partial, reason, termination = (
                            True,
                            record.reason
                            if record and record.reason
                            else "phase gate inconclusive",
                            AssessmentTermination.FAILURE,
                        )
                        break
                else:
                    active_phase = None
        except BaseException as error:
            termination, cleanup_mode = _termination(error)
            partial = True
            reason = _exception_reason(error)
            self._interrupt_running_checks()
            if active_phase is not None:
                previous = self._manifest.state().gate_record(active_phase)
                self._manifest.append_phase_finished(
                    active_phase,
                    PhaseState.INTERRUPTED
                    if termination is not AssessmentTermination.FAILURE
                    else PhaseState.FAILED,
                    GateStatus.INCONCLUSIVE,
                    (),
                    reason,
                    supersedes=previous.record_id if previous else None,
                )
            cleanup_error = self._cleanup_owned(cleanup_mode)
            cleanup_performed = True
            if cleanup_error:
                reason = f"{reason}; {cleanup_error}"
        finally:
            if (
                partial
                and termination is not AssessmentTermination.SUCCESS
                and not cleanup_performed
            ):
                cleanup_error = self._cleanup_owned(_cleanup_mode(termination))
                cleanup_performed = True
                if cleanup_error and cleanup_error not in reason:
                    reason = f"{reason}; {cleanup_error}"
            try:
                comparison_record = guard.finalize(termination)
                comparison_preserved = comparison_record.comparison.preservation_confirmed
                if not comparison_preserved:
                    partial = True
                    reason = f"{reason}; final source comparison did not confirm preservation"
            except BaseException as error:
                partial = True
                comparison_preserved = False
                reason = f"{reason}; final source comparison failed: {_exception_reason(error)}"

        report_ref = self._write_partial(reason, comparison_preserved) if partial else None
        reached = tuple(
            phase
            for phase in AssessmentPhase
            if self._manifest.state().gate_for(phase) is GateStatus.GREEN
        )
        return PipelineResult(partial, reason, reached, report_ref, comparison_preserved)

    def _execute_phase(self, action: PhaseAction) -> None:
        state = self._manifest.state()
        prior_gate = state.gate_record(action.phase)
        self._manifest.append_phase_started(action.phase)
        for check_id in action.planned_check_ids:
            prior = self._manifest.state().check_record(check_id)
            self._manifest.append_check(
                action.phase,
                check_id,
                CheckState.RUNNING,
                supersedes=prior.record_id if prior else None,
            )
        result = action.execute(
            PhaseExecutionContext(action.phase, self._cancellation, self._manifest)
        )
        execution_admitted: bool | None = None
        if action.phase is AssessmentPhase.DISCOVERY_ADMISSION:
            admission = result.execution_admission
            execution_admitted = admission.admitted if admission is not None else False
            if result.gate is GateStatus.GREEN and not execution_admitted:
                # Controls 1.5/1.9: execution safety ambiguity blocks before launch.
                raise ValueError(
                    "discovery/admission did not establish every execution safety control"
                )
        if {item.check_id for item in result.checks} != set(action.planned_check_ids):
            # Verification control: missing completion is never inferred as verified.
            raise ValueError("phase did not resolve every planned check")
        for completion in result.checks:
            running = self._manifest.state().check_record(completion.check_id)
            self._manifest.append_check(
                action.phase,
                completion.check_id,
                CheckState.VERIFIED if completion.verified else CheckState.UNVERIFIED,
                completion.evidence_ref,
                running.record_id if running else None,
            )
        phase_state = (
            PhaseState.COMPLETED if result.gate is GateStatus.GREEN else PhaseState.BLOCKED
        )
        self._manifest.append_phase_finished(
            action.phase,
            phase_state,
            result.gate,
            result.artifact_refs,
            result.reason,
            supersedes=prior_gate.record_id if prior_gate else None,
            execution_admitted=execution_admitted,
        )

    def _ordering_error(self, state: ReconstructedRunState, phase: AssessmentPhase) -> str | None:
        for predecessor in predecessor_phases(phase):
            if state.gate_for(predecessor) is not GateStatus.GREEN:
                return f"hard gate blocked {phase.value}: {predecessor.value} is not green"
        if phase is AssessmentPhase.MIRROR_EXECUTION:
            admission = state.gate_record(AssessmentPhase.DISCOVERY_ADMISSION)
            if admission is None or admission.execution_admitted is not True:
                # Controls 1.5/1.9: missing persisted proof cannot authorize execution.
                return "hard gate blocked mirror execution: safety admission is not established"
        return None

    def _interrupt_running_checks(self) -> None:
        for record in self._manifest.state().running_checks:
            self._manifest.append_check(
                record.phase or AssessmentPhase.BASELINE,
                record.check_id or "unknown-check",
                CheckState.UNVERIFIED,
                supersedes=record.record_id,
            )

    def _recover_stale_attempts(self) -> str | None:
        if not self._manifest.state().running_checks:
            return None
        self._interrupt_running_checks()
        cleanup_error = self._cleanup_owned(CleanupMode.ABORT)
        return "recovered interrupted checks as unverified" + (
            f"; {cleanup_error}" if cleanup_error else ""
        )

    def _cleanup_owned(self, mode: CleanupMode) -> str | None:
        state = self._manifest.state()
        try:
            # Ownership controls 4.7/4.8: foreign/live-system processes are never inputs.
            result = self._cleanup(
                state.identity.ownership_token,
                state.owned_processes,
                mode,
            )
            return None if result.cleanup_completed else "owned-process cleanup was incomplete"
        except Exception as error:
            return f"owned-process cleanup failed: {_exception_reason(error)}"

    def _write_partial(self, reason: str, comparison_preserved: bool) -> str:
        state = self._manifest.state()
        target = self._manifest.path.parent / f"partial-report-{len(state.records):06d}.md"
        text = render_partial_assessment_report(state, reason, comparison_preserved)
        with target.open("x", encoding="utf-8", newline="\n") as report:
            # Publication control: exclusive creation prevents silent report replacement.
            report.write(text)
            report.flush()
            os.fsync(report.fileno())
        self._manifest.append_partial_report(str(target), reason)
        return str(target)


def _termination(error: BaseException) -> tuple[AssessmentTermination, CleanupMode]:
    if isinstance(error, TimeoutError):
        return AssessmentTermination.TIMEOUT, CleanupMode.TIMEOUT
    if isinstance(error, KeyboardInterrupt):
        return AssessmentTermination.ABORT, CleanupMode.ABORT
    return AssessmentTermination.FAILURE, CleanupMode.FAILURE


def _cleanup_mode(termination: AssessmentTermination) -> CleanupMode:
    return CleanupMode(termination.value)


def _exception_reason(error: BaseException) -> str:
    text = str(error).strip()
    return f"{type(error).__name__}: {text}" if text else type(error).__name__
