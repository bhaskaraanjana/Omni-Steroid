"""Expose run/resume orchestration and phase bounds through an argparse CLI.

The CLI allocates or reopens only the append manifest. Existing stage adapters are
injected by execution tasks, so missing wiring fails closed before assessment activity.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from secrets import token_hex

from .assessment_phase_gates import AssessmentPhase, parse_phase
from .assessment_pipeline import AssessmentPipeline
from .assessment_pipeline_models import PipelineOptions
from .model_types import ZonedTimestamp
from .run_manifest_append_store import AppendOnlyRunManifest, RunIdentity

PipelineBuilder = Callable[["CLIRequest", AppendOnlyRunManifest], AssessmentPipeline]


@dataclass(frozen=True, slots=True)
class CLIRequest:
    """Validated command-line request passed to the stage-adapter composition root."""

    command: str
    manifest_path: Path
    phase_limit: AssessmentPhase | None
    observation_only: bool
    run_identity: RunIdentity | None


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the public run/resume CLI with explicit safety bounds."""
    parser = argparse.ArgumentParser(prog="omni-repository-assessor")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="start a new append-only assessment run")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--run-id", required=True)
    run.add_argument("--source-root", required=True)
    run.add_argument("--temporary-root", required=True)
    run.add_argument("--output-root", required=True)
    run.add_argument("--ownership-token", default=None)
    _add_limits(run)

    resume = subparsers.add_parser("resume", help="resume from manifest state alone")
    resume.add_argument("--manifest", type=Path, required=True)
    _add_limits(resume)
    return parser


def execute_cli(request: CLIRequest, pipeline_builder: PipelineBuilder) -> int:
    """Create/reopen the manifest, run the injected stages, and return a stable code."""
    if request.command == "run":
        if request.run_identity is None:
            raise ValueError("run requires a run identity")
        store = AppendOnlyRunManifest.create(
            request.manifest_path,
            request.run_identity,
            clock=_local_now,
        )
    elif request.command == "resume":
        if request.run_identity is not None:
            raise ValueError("resume reconstructs identity from the manifest")
        store = AppendOnlyRunManifest.open(request.manifest_path, clock=_local_now)
    else:
        raise ValueError(f"unsupported command: {request.command}")
    pipeline = pipeline_builder(request, store)
    result = pipeline.run(PipelineOptions(request.phase_limit, request.observation_only))
    return 2 if result.partial else 0


def main(
    argv: Sequence[str] | None = None,
    pipeline_builder: PipelineBuilder | None = None,
) -> int:
    """Parse CLI arguments and fail closed when stage adapters are not composed."""
    parser = build_argument_parser()
    namespace = parser.parse_args(argv)
    request = _request(namespace)
    if pipeline_builder is None:
        from .observation_pipeline import build_observation_pipeline

        pipeline_builder = build_observation_pipeline
    return execute_cli(request, pipeline_builder)


def _add_limits(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--phase-limit",
        type=_phase_argument,
        default=None,
        metavar="PHASE",
        help=(
            "stop after baseline, claims, discovery/admission, mirror execution, "
            "local e2e, native integration, normalization, parity, or report"
        ),
    )
    parser.add_argument(
        "--observation-only",
        action="store_true",
        help="stop after discovery/admission and launch no assessment process",
    )


def _phase_argument(value: str) -> AssessmentPhase:
    try:
        return parse_phase(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _request(namespace: argparse.Namespace) -> CLIRequest:
    command = str(namespace.command)
    identity: RunIdentity | None = None
    if command == "run":
        token_value = namespace.ownership_token
        token = str(token_value) if token_value else f"assessment-{token_hex(16)}"
        identity = RunIdentity(
            str(namespace.run_id),
            str(namespace.source_root),
            str(namespace.temporary_root),
            str(namespace.output_root),
            token,
        )
    return CLIRequest(
        command,
        Path(namespace.manifest),
        namespace.phase_limit,
        bool(namespace.observation_only),
        identity,
    )


def _local_now() -> ZonedTimestamp:
    return ZonedTimestamp(datetime.now().astimezone())


if __name__ == "__main__":
    raise SystemExit(main())
