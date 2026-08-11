"""Discover primary documents and extract exact, independently verifiable claims.

The inventory is deliberately read-only and deterministic. It records source text
verbatim while normalized material scopes remain separate assessment metadata.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Iterable

from .claim_models import DocumentaryClaim
from .model_types import SourceLocation


class PrimaryDocumentCategory(StrEnum):
    """Required classes of primary documentary claim sources."""

    OVERVIEW = "overview"
    FEATURE = "feature"
    ARCHITECTURE = "architecture"
    SECURITY_PRIVACY = "security_privacy"
    PACKAGING_RELEASE = "packaging_release"
    EVIDENCE_RESULTS = "evidence_results"


@dataclass(frozen=True, slots=True)
class PrimaryClaimDocument:
    """One primary repository document selected for claim extraction."""

    path: str
    category: PrimaryDocumentCategory


_EXCLUDED_PARTS = {
    ".git", ".venv", "node_modules", "target", "dist", "build",
    "assessment-output", "__pycache__", "plans", "progress", "research",
}


def _document_category(relative: str) -> PrimaryDocumentCategory | None:
    """Classify primary documents by repository role, never by generated content."""
    path = Path(relative)
    lowered = relative.lower()
    name = path.name.lower()
    parts = {part.lower() for part in path.parts}
    if parts & _EXCLUDED_PARTS:
        return None
    if relative in {"README.md", "PRODUCT.md"}:
        return PrimaryDocumentCategory.OVERVIEW
    if lowered == "docs/features.md" or name in {"features.md", "feature-catalog.md"}:
        return PrimaryDocumentCategory.FEATURE
    if lowered == "docs/architecture.md" or name in {"architecture.md", "architecture-overview.md"}:
        return PrimaryDocumentCategory.ARCHITECTURE
    if name == "security.md" or any(token in name for token in ("security", "privacy", "threat-model")):
        return PrimaryDocumentCategory.SECURITY_PRIVACY
    if path.parts and path.parts[0].lower() == "packaging":
        return PrimaryDocumentCategory.PACKAGING_RELEASE
    if any(token in name for token in ("release", "installer", "packaging")):
        return PrimaryDocumentCategory.PACKAGING_RELEASE
    if path.parts and path.parts[0].lower() == "evidence":
        return PrimaryDocumentCategory.EVIDENCE_RESULTS
    if any(token in name for token in ("evidence", "results", "coverage-report")):
        return PrimaryDocumentCategory.EVIDENCE_RESULTS
    return None


def discover_primary_claim_documents(repository_root: Path) -> tuple[PrimaryClaimDocument, ...]:
    """Discover all present primary Markdown claim sources in required categories."""
    root = repository_root.resolve()
    documents: list[PrimaryClaimDocument] = []
    for path in root.rglob("*.md"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        category = _document_category(relative)
        if category is not None:
            documents.append(PrimaryClaimDocument(relative, category))
    return tuple(sorted(documents, key=lambda item: (item.category.value, item.path)))


def _markdown_units(text: str) -> Iterable[tuple[str, int, int]]:
    """Yield non-code Markdown blocks with inclusive source line locations."""
    lines = text.splitlines()
    block: list[str] = []
    block_start = 0
    in_fence = False

    def flush(end_line: int) -> Iterable[tuple[str, int, int]]:
        nonlocal block, block_start
        if block:
            raw = "\n".join(block).strip()
            if raw:
                yield raw, block_start, end_line
            block = []
            block_start = 0

    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            yield from flush(index - 1)
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        standalone = stripped.startswith(("|", "- ", "* ", "> "))
        ignored = not stripped or stripped.startswith(("#", "<!--", "![", "<"))
        if ignored or standalone:
            yield from flush(index - 1)
            if standalone:
                yield stripped, index, index
            continue
        if not block:
            block_start = index
        block.append(line)
    yield from flush(len(lines))


_SENTENCE = re.compile(r".+?(?:[.!?](?=\s|$)|$)", re.DOTALL)
_MATERIAL_TERMS = re.compile(
    r"\b(?:captur(?:e|es|ed|ing)|record(?:s|ed|ing)?|transcrib(?:e|es|ed|ing)|meetings?|notes?|ask|search|retriev|export|"
    r"privacy|security|telemetry|keys?|approval|audit|vault|platform|windows|macos|linux|"
    r"install|packag|release|build|test|coverage|accuracy|latency|quality|provider|local)\b",
    re.IGNORECASE,
)
_NON_CLAIM_TERMS = re.compile(r"\b(?:introduces?|documentation|table of contents|read more)\b", re.IGNORECASE)
_LINE_TARGET = re.compile(r"(?:90\s*%[^\n]*line|line[^\n]*90\s*%)", re.IGNORECASE)
_BRANCH_TARGET = re.compile(r"(?:85\s*%[^\n]*branch|branch[^\n]*85\s*%)", re.IGNORECASE)


def _sentences(raw: str, start_line: int) -> Iterable[tuple[str, int, int]]:
    for match in _SENTENCE.finditer(raw):
        exact = match.group(0).strip()
        if not exact:
            continue
        prefix = raw[: match.start()]
        claim_start = start_line + prefix.count("\n")
        claim_end = claim_start + exact.count("\n")
        yield exact, claim_start, claim_end


def _material_scope(exact_text: str) -> str | None:
    normalized = re.sub(r"[`*_>|-]", " ", exact_text).strip()
    if not _MATERIAL_TERMS.search(normalized) or _NON_CLAIM_TERMS.search(normalized):
        return None
    lowered = normalized.lower()
    if "capture" in lowered or "record" in lowered:
        return "capability.capture"
    if "transcrib" in lowered:
        return "capability.transcription"
    if "security" in lowered or "privacy" in lowered or "telemetry" in lowered:
        return "safety.security_privacy"
    if any(term in lowered for term in ("installer", "packaging", "release", "update")):
        return "release.packaging"
    if any(term in lowered for term in ("windows", "macos", "linux", "platform")):
        return "platform.support"
    if any(term in lowered for term in ("coverage", "accuracy", "latency", "quality", "test")):
        return "quality.level"
    return "capability.product"


def _claim_id(path: str, start: int, end: int, scope: str, exact: str) -> str:
    payload = f"{path}\0{start}\0{end}\0{scope}\0{exact}".encode("utf-8")
    return "claim-" + hashlib.sha256(payload).hexdigest()[:20]


def extract_material_claims(
    repository_root: Path,
    documents: Iterable[PrimaryClaimDocument],
) -> tuple[DocumentaryClaim, ...]:
    """Split verifiable material statements while retaining exact source text/ranges."""
    root = repository_root.resolve()
    claims: list[DocumentaryClaim] = []
    for document in sorted(documents, key=lambda item: item.path):
        text = (root / document.path).read_text(encoding="utf-8")
        for block, block_start, _block_end in _markdown_units(text):
            for exact, start, end in _sentences(block, block_start):
                target_scopes: list[str] = []
                if _LINE_TARGET.search(exact):
                    target_scopes.append("quality.coverage.line.target")
                if _BRANCH_TARGET.search(exact):
                    target_scopes.append("quality.coverage.branch.target")
                scopes = target_scopes or [_material_scope(exact)]
                for scope in scopes:
                    if scope is None:
                        continue
                    location = SourceLocation(document.path, start, end)
                    claims.append(
                        DocumentaryClaim(
                            claim_id=_claim_id(document.path, start, end, scope, exact),
                            exact_text=exact,
                            source=location,
                            material_scope=scope,
                        )
                    )
    return tuple(claims)
