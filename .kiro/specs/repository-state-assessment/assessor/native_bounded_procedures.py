"""Bounded procedure bodies for the natively executable hardware scopes.

Each body drives the repository's own production module rather than a
reimplementation, runs exactly once, uses only synthetic non-private input, and
writes only inside the contained child's assessment-owned data root. Scopes whose
preflights block never reach this module.
"""

from __future__ import annotations

from .hardware_status import HardwareScope

_GRAPHICS_PROCESSOR_SOURCE = '''
import json
from engine.stt.stt_runtime_status import detect_inference_device

device = detect_inference_device()
name = None
capability = None
if device == "cuda":
    import torch

    name = torch.cuda.get_device_name(0)
    capability = ".".join(str(part) for part in torch.cuda.get_device_capability(0))
print(json.dumps({
    "compute_device": device,
    "graphics_processor": name,
    "compute_capability": capability,
    "inference_executed": False,
    "observable": "graphics processor selected and identified",
}))
'''

_FALLBACK_RETRIEVAL_SOURCE = '''
import asyncio, json, os, time
from pathlib import Path

import aiosqlite

from engine.index.hybrid_rrf_retriever import HybridRrfRetriever
from engine.storage.sqlite_migrations_runner import apply_migrations

CORPUS = [
    ("Quarterly Planning", "The synthetic planning note records a budget review milestone."),
    ("Release Checklist", "The synthetic checklist note records a packaging and signing step."),
    ("Retrieval Notes", "The synthetic retrieval note records a keyword ranking experiment."),
]
QUERY = "synthetic keyword ranking experiment"


async def main():
    database = Path(os.environ["OMNI_DB_PATH"])
    database.parent.mkdir(parents=True, exist_ok=True)
    await apply_migrations(database, Path("migrations").resolve(strict=True))
    async with aiosqlite.connect(database) as connection:
        for index, (title, body) in enumerate(CORPUS, start=1):
            await connection.execute(
                "INSERT INTO chunks (note_path, source_type, note_title, heading_path,"
                " line_start, line_end, char_start, char_end, text, contextualized_text,"
                " mtime) VALUES (?, 'vault', ?, '', 1, 1, 0, ?, ?, ?, 0.0)",
                (f"synthetic/{index}.md", title, len(body), body, f"{title} > {body}"),
            )
        await connection.commit()
        started = time.monotonic()
        # Dense side explicitly configured absent: this is the documented
        # keyword-only fallback tier, not a degraded hybrid run.
        results = await HybridRrfRetriever(connection, None, None).retrieve(QUERY, top_n=3)
        elapsed_ms = int((time.monotonic() - started) * 1000)
    print(json.dumps({
        "tier": "fts5_bm25_keyword_only",
        "dense_tier_participated": False,
        "retrievals_executed": 1,
        "corpus_size": len(CORPUS),
        "result_count": len(results),
        "top_note_path": results[0].note_path if results else None,
        "retrieval_source": results[0].retrieval_source if results else None,
        "elapsed_ms": elapsed_ms,
        "observable": "one fallback retrieval completed",
    }))


asyncio.run(main())
'''

EXECUTABLE_PROCEDURE_SOURCES = {
    HardwareScope.GRAPHICS_PROCESSOR_SELECTION: _GRAPHICS_PROCESSOR_SOURCE,
    HardwareScope.FALLBACK_RETRIEVAL: _FALLBACK_RETRIEVAL_SOURCE,
}


def procedure_source(scope: HardwareScope) -> str | None:
    """Return the bounded body for a scope the assessment can execute itself."""
    return EXECUTABLE_PROCEDURE_SOURCES.get(scope)
