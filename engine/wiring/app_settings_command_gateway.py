"""Settings gateway: ``settings.get`` / ``settings.update`` / ``setup.status``.

Purpose: the server-layer object behind the M7 settings surface — reads and
writes the ``app_settings`` table (validated, all-or-nothing), applies the
runtime side effects (vault env mirror, kill-switch runtime override), and
reports the honest first-run setup state the onboarding wizard gates on.
Pipeline position: constructed by ``engine.server``'s app factory (inert —
no I/O until a command arrives); driven by
``engine.wiring.app_settings_command_dispatcher``.

Security invariants:
- Every value passes ``validate_settings_values`` BEFORE any write (deny by
  default; all-or-nothing so a half-applied batch cannot exist).
- ``setup.status`` reports key PRESENCE only (booleans) — key material
  never rides the wire in any direction on this surface.
- The kill-switch runtime override engages immediately on update (fail
  closed on egress without a restart).
"""

import os
from collections.abc import Callable
from pathlib import Path

from engine.detect.detection_signal_types import DEFAULT_AUTO_START_SOURCES
from engine.enhance.note_templates import AUTO_TEMPLATE_ID, BUILTIN_TEMPLATES
from engine.google.dpapi_google_token_store import GoogleTokenStore
from engine.microsoft.dpapi_microsoft_token_store import MicrosoftTokenStore
from engine.router.completion_contract import TaskType
from engine.router.router_errors import MisconfiguredRouteError
from engine.router.routing_table import resolve_route
from engine.security.kill_switch import kill_switch_engaged, set_kill_switch_runtime_override
from engine.security.provider_key_store import ProviderKeyStore
from engine.storage.app_settings_repository import (
    SETTING_ACTIVE_TEMPLATE,
    SETTING_AEC_ENABLED,
    SETTING_AUTO_SUMMARY,
    SETTING_AUTOSTOP_SILENCE_S,
    SETTING_CARTESIA_VOICE_ID,
    SETTING_CUSTOM_TEMPLATES,
    SETTING_DETECTION_AUTO_START_SOURCES,
    SETTING_DICTATION_CLEANUP_STYLE,
    SETTING_DISCLOSURE_REMINDER,
    SETTING_INSTANT_EXECUTE_WHITELIST,
    SETTING_KEEP_AUDIO,
    SETTING_KILL_SWITCH,
    SETTING_LIVE_CAPTIONS_OVERLAY,
    SETTING_LIVE_TRANSLATION_LANG,
    SETTING_MIC_DEVICE_ID,
    SETTING_OLLAMA_BASE_URL,
    SETTING_ONBOARDING_COMPLETE,
    SETTING_PUSH_TO_TALK_HOTKEY,
    SETTING_SELECTION_TRANSLATION_LANG,
    SETTING_SPEAKER_IDENTITY,
    SETTING_SPEAKER_VOICE_EMBEDDING,
    SETTING_STT_ENGINE,
    SETTING_STT_MODEL_ID,
    SETTING_STT_OPENAI_BASE_URL,
    SETTING_SUMMARY_LANGUAGE,
    SETTING_SUMMARY_MODEL_ID,
    SETTING_SUMMARY_PROVIDER,
    SETTING_VAULT_DIR,
    read_all_settings,
    write_setting,
)
from engine.storage.sqlite_connection import open_sqlite_connection
from engine.storage.sqlite_migrations_runner import apply_migrations
from engine.stt.model_weights_downloader import MODEL_SPECS, models_directory
from engine.stt.silence_auto_stop_monitor import AUTOSTOP_SILENCE_ENV_VAR
from engine.vault.vault_paths import VAULT_DIR_ENV_VAR
from engine.wiring.settings_value_validation import (
    SettingsValueError,
    validate_settings_values,
)

# Defaults reported by settings.get for keys never written. keep_audio is
# TRUE by default (recordings are kept as MP3 alongside the transcript; the
# user can opt out in Privacy). The hotkey default mirrors the Rust shell's
# DICTATION_HOLD_KEY ("F9").
SETTINGS_DEFAULTS: dict[str, object] = {
    SETTING_VAULT_DIR: None,
    SETTING_PUSH_TO_TALK_HOTKEY: "F9",
    SETTING_KEEP_AUDIO: True,
    SETTING_DISCLOSURE_REMINDER: True,
    SETTING_KILL_SWITCH: False,
    SETTING_INSTANT_EXECUTE_WHITELIST: [],
    SETTING_ACTIVE_TEMPLATE: AUTO_TEMPLATE_ID,
    SETTING_CUSTOM_TEMPLATES: [],
    SETTING_ONBOARDING_COMPLETE: False,
    SETTING_DETECTION_AUTO_START_SOURCES: sorted(DEFAULT_AUTO_START_SOURCES),
    SETTING_AUTOSTOP_SILENCE_S: 0,
    SETTING_LIVE_CAPTIONS_OVERLAY: True,
    SETTING_AEC_ENABLED: False,
    SETTING_LIVE_TRANSLATION_LANG: "",
    SETTING_SUMMARY_LANGUAGE: "",
    SETTING_SUMMARY_MODEL_ID: "llama3.2",
    SETTING_SPEAKER_IDENTITY: "Me",
    SETTING_SPEAKER_VOICE_EMBEDDING: "",
    SETTING_DICTATION_CLEANUP_STYLE: "classic",
    SETTING_STT_ENGINE: "parakeet",
    SETTING_STT_MODEL_ID: "",
    SETTING_STT_OPENAI_BASE_URL: "",
    SETTING_SELECTION_TRANSLATION_LANG: "English",
    SETTING_OLLAMA_BASE_URL: "http://127.0.0.1:11434",
    SETTING_SUMMARY_PROVIDER: "ollama",
    SETTING_AUTO_SUMMARY: False,
    SETTING_CARTESIA_VOICE_ID: "",
    SETTING_MIC_DEVICE_ID: "",
}

# On-device rows shown alongside the routed tasks: transcription and
# embeddings NEVER leave the machine (local-only invariant) — the matrix
# states it as data, not decoration.
_ON_DEVICE_ROWS: tuple[dict[str, object], ...] = (
    {
        "task": "transcription",
        "on_device": True,
        "attempts": [{"provider": "local", "model": "parakeet-tdt-0.6b-v2"}],
        "budget_ms": None,
    },
    {
        "task": "embeddings",
        "on_device": True,
        "attempts": [{"provider": "local", "model": "bge-small-en-v1.5"}],
        "budget_ms": None,
    },
)


class SettingsCommandRefused(Exception):
    """Honest refusal (unknown key / malformed value) — the dispatcher
    turns it into a typed ``settings_error`` reply."""


class AppSettingsCommandGateway:
    """One per engine process; construction is inert (no keys, no I/O).

    Every command opens its own connection (schema ensured first), works,
    and closes — the same per-request lifecycle as the other gateways.
    """

    def __init__(
        self,
        db_path: Path,
        migrations_dir: Path,
        key_store: ProviderKeyStore | None = None,
        models_dir: Path | None = None,
        google_token_store: GoogleTokenStore | None = None,
        microsoft_token_store: MicrosoftTokenStore | None = None,
    ) -> None:
        self._db_path = db_path
        self._migrations_dir = migrations_dir
        self._key_store = key_store if key_store is not None else ProviderKeyStore()
        self._models_dir = models_dir
        self._google_token_store = (
            google_token_store if google_token_store is not None else GoogleTokenStore()
        )
        self._microsoft_token_store = (
            microsoft_token_store if microsoft_token_store is not None else MicrosoftTokenStore()
        )
        self._on_detection_settings_applied: Callable[[dict[str, object]], None] | None = None
        self._on_live_translation_settings_applied: Callable[[dict[str, object]], None] | None = (
            None
        )
        self._on_vault_dir_applied: Callable[[str], None] | None = None

    def set_detection_settings_listener(
        self, listener: Callable[[dict[str, object]], None] | None
    ) -> None:
        """Optional hook: detection rules hot-reload when settings change."""
        self._on_detection_settings_applied = listener

    def set_live_translation_settings_listener(
        self, listener: Callable[[dict[str, object]], None] | None
    ) -> None:
        """Optional hook: live translation lang hot-reloads mid-session."""
        self._on_live_translation_settings_applied = listener

    def set_vault_dir_listener(self, listener: Callable[[str], None] | None) -> None:
        """Optional hook: vault watcher rebinds when vault_dir changes."""
        self._on_vault_dir_applied = listener

    # ------------------------------------------------------------- plumbing
    async def _read_effective_settings(self) -> dict[str, object]:
        """Stored values over defaults; vault_dir falls back to the env
        (the honest current truth in dev, where .env supplies it)."""
        await apply_migrations(self._db_path, self._migrations_dir)
        connection = await open_sqlite_connection(self._db_path)
        try:
            stored = await read_all_settings(connection)
        finally:
            await connection.close()
        effective = dict(SETTINGS_DEFAULTS)
        effective.update(stored)
        if effective[SETTING_VAULT_DIR] is None:
            env_vault = os.environ.get(VAULT_DIR_ENV_VAR, "").strip()
            if env_vault:
                effective[SETTING_VAULT_DIR] = env_vault
        return effective

    def _routing_rows(self) -> list[dict[str, object]]:
        """The REAL resolved routing policy for the current keyed world."""
        keyed = self._key_store.keyed_providers()
        rows: list[dict[str, object]] = list(_ON_DEVICE_ROWS)
        for task in TaskType:
            try:
                route = resolve_route(task.value, keyed)
                attempts: list[dict[str, object]] = [
                    {"provider": slot.provider.value, "model": slot.model}
                    for slot in route.attempts
                ]
                budget: int | None = route.latency_budget_p95_ms
            except MisconfiguredRouteError:
                attempts = []  # honest: no keyed provider can serve this task
                budget = None
            rows.append(
                {
                    "task": task.value,
                    "on_device": False,
                    "attempts": attempts,
                    "budget_ms": budget,
                }
            )
        return rows

    def _template_options(self, custom_templates: object) -> list[dict[str, object]]:
        options: list[dict[str, object]] = [
            {"template_id": AUTO_TEMPLATE_ID, "display_name": "Auto", "builtin": True}
        ]
        options.extend(
            {"template_id": t.template_id, "display_name": t.display_name, "builtin": True}
            for t in BUILTIN_TEMPLATES.values()
        )
        if isinstance(custom_templates, list):
            options.extend(
                {
                    "template_id": str(entry.get("template_id", "")),
                    "display_name": str(entry.get("display_name", "")),
                    "builtin": False,
                }
                for entry in custom_templates
                if isinstance(entry, dict)
            )
        return options

    # ------------------------------------------------------------- commands
    async def get_settings_payload(self) -> dict[str, object]:
        """settings.get -> {settings, kill_switch_engaged, routing,
        template_options} — everything real, nothing invented."""
        effective = await self._read_effective_settings()
        settings_out = dict(effective)
        embedding = settings_out.pop(SETTING_SPEAKER_VOICE_EMBEDDING, "")
        settings_out["speaker_voice_enrolled"] = (
            bool(str(embedding).strip()) if embedding else False
        )
        return {
            "settings": settings_out,
            # The LIVE truth (env + runtime override), not just the stored
            # preference — the status display must never contradict reality.
            "kill_switch_engaged": kill_switch_engaged(),
            "routing": self._routing_rows(),
            "template_options": self._template_options(
                effective[SETTING_CUSTOM_TEMPLATES]
            ),
        }

    async def update_settings(self, values: dict[str, object]) -> dict[str, object]:
        """Validate the whole batch, persist it, apply side effects.

        Returns the normalised applied map. Raises
        :class:`SettingsCommandRefused` with the plain reason on any
        invalid key/value (nothing persisted in that case).
        """
        try:
            normalized = validate_settings_values(values)
        except SettingsValueError as exc:
            raise SettingsCommandRefused(str(exc)) from exc
        await apply_migrations(self._db_path, self._migrations_dir)
        connection = await open_sqlite_connection(self._db_path)
        try:
            # One transaction: the batch lands whole or not at all.
            await connection.execute("BEGIN IMMEDIATE")
            try:
                for key, value in normalized.items():
                    await write_setting(connection, key, value)
                await connection.execute("COMMIT")
            except Exception:
                await connection.execute("ROLLBACK")
                raise
        finally:
            await connection.close()
        self._apply_side_effects(normalized)
        await self._notify_detection_settings_listener()
        await self._notify_live_translation_settings_listener()
        return normalized

    async def _notify_detection_settings_listener(self) -> None:
        if self._on_detection_settings_applied is None:
            return
        effective = await self._read_effective_settings()
        self._on_detection_settings_applied(effective)

    async def _notify_live_translation_settings_listener(self) -> None:
        if self._on_live_translation_settings_applied is None:
            return
        effective = await self._read_effective_settings()
        self._on_live_translation_settings_applied(effective)

    def _apply_side_effects(self, applied: dict[str, object]) -> None:
        """Runtime effects after a successful persist (order-independent)."""
        vault_dir = applied.get(SETTING_VAULT_DIR)
        if isinstance(vault_dir, str):
            # Vault resolution reads this env var everywhere; the explicit
            # user choice takes effect immediately, no restart.
            os.environ[VAULT_DIR_ENV_VAR] = vault_dir
            if self._on_vault_dir_applied is not None:
                self._on_vault_dir_applied(vault_dir)
        kill = applied.get(SETTING_KILL_SWITCH)
        if isinstance(kill, bool):
            # Fail closed on egress instantly — the router consults this
            # before every external call.
            set_kill_switch_runtime_override(kill)
        silence_s = applied.get(SETTING_AUTOSTOP_SILENCE_S)
        if isinstance(silence_s, int):
            os.environ[AUTOSTOP_SILENCE_ENV_VAR] = str(silence_s)
        ollama_url = applied.get(SETTING_OLLAMA_BASE_URL)
        if isinstance(ollama_url, str) and ollama_url.strip():
            # Meetily-style: Settings endpoint makes Ollama routable immediately.
            from engine.router.provider_client_registry import OLLAMA_BASE_URL_ENV

            os.environ[OLLAMA_BASE_URL_ENV] = ollama_url.strip()
        voice_id = applied.get(SETTING_CARTESIA_VOICE_ID)
        if isinstance(voice_id, str):
            # Setting wins when non-empty; clearing the setting pops the env so
            # a stale CARTESIA_VOICE_ID cannot keep driving Naomi's voice.
            from engine.voice.cartesia_credentials import CARTESIA_VOICE_ID_ENV_VAR

            stripped = voice_id.strip()
            if stripped:
                os.environ[CARTESIA_VOICE_ID_ENV_VAR] = stripped
            else:
                os.environ.pop(CARTESIA_VOICE_ID_ENV_VAR, None)

    async def apply_persisted_settings_at_boot(self) -> None:
        """Boot hook (production only): make persisted settings effective.

        - vault_dir: when the DB has a non-empty vault_dir, always mirror it
          into OMNI_VAULT_DIR (user setting wins over a stale env value).
        - kill_switch: a stored True engages the runtime override (a stored
          False leaves the env flag in charge — never weakens the control).
        """
        effective = await self._read_effective_settings()
        stored_vault = effective.get(SETTING_VAULT_DIR)
        if isinstance(stored_vault, str) and stored_vault.strip():
            os.environ[VAULT_DIR_ENV_VAR] = stored_vault
        if effective.get(SETTING_KILL_SWITCH) is True:
            # Fail closed: a user-engaged switch survives restarts.
            set_kill_switch_runtime_override(True)
        silence_s = effective.get(SETTING_AUTOSTOP_SILENCE_S)
        if isinstance(silence_s, int):
            os.environ[AUTOSTOP_SILENCE_ENV_VAR] = str(silence_s)
        if self._on_detection_settings_applied is not None:
            self._on_detection_settings_applied(effective)
        if self._on_live_translation_settings_applied is not None:
            self._on_live_translation_settings_applied(effective)
        ollama_url = effective.get(SETTING_OLLAMA_BASE_URL)
        if isinstance(ollama_url, str) and ollama_url.strip():
            from engine.router.provider_client_registry import OLLAMA_BASE_URL_ENV

            os.environ[OLLAMA_BASE_URL_ENV] = ollama_url.strip()
        voice_id = effective.get(SETTING_CARTESIA_VOICE_ID)
        if isinstance(voice_id, str) and voice_id.strip():
            from engine.voice.cartesia_credentials import CARTESIA_VOICE_ID_ENV_VAR

            os.environ[CARTESIA_VOICE_ID_ENV_VAR] = voice_id.strip()

    async def setup_status_payload(self) -> dict[str, object]:
        """setup.status -> the honest first-run state of THIS machine."""
        effective = await self._read_effective_settings()
        keys = {
            provider: self._key_store.get_key(provider) is not None
            for provider in (
                "groq",
                "gemini",
                "anthropic",
                "openai",
                "openrouter",
                "azure_openai",
                "cartesia",
            )
        }
        vault_dir = effective.get(SETTING_VAULT_DIR)
        vault_configured = isinstance(vault_dir, str) and Path(vault_dir).is_dir()
        models_dir = self._models_dir if self._models_dir is not None else models_directory()
        core_models = [
            {
                "file": spec.filename,
                "present": (models_dir / spec.filename).is_file(),
                "bytes": (
                    (models_dir / spec.filename).stat().st_size
                    if (models_dir / spec.filename).is_file()
                    else 0
                ),
            }
            for spec in MODEL_SPECS
        ]
        from engine.stt.whisper_model_catalog import whisper_models_status

        whisper_models = whisper_models_status(models_dir)
        models = [*core_models, *whisper_models]
        try:
            google_connected = self._google_token_store.load_tokens() is not None
        except Exception:
            google_connected = False  # a corrupt blob reads as not connected
        try:
            microsoft_connected = self._microsoft_token_store.load_tokens() is not None
        except Exception:
            microsoft_connected = False
        onboarding_complete = effective.get(SETTING_ONBOARDING_COMPLETE) is True
        # The product's required pair is Groq + Gemini; Anthropic/Cartesia
        # are optional slots (session decision — never required to ship).
        # Whisper sizes are optional Enhanced STT — not part of setup_complete.
        setup_complete = (
            keys["groq"]
            and keys["gemini"]
            and vault_configured
            and all(bool(m["present"]) for m in core_models)
        )
        return {
            "keys": keys,
            "vault": {
                "configured": vault_configured,
                "path": vault_dir if vault_configured else None,
            },
            "models": models,
            "google_connected": google_connected,
            "microsoft_connected": microsoft_connected,
            "onboarding_complete": onboarding_complete,
            "setup_complete": setup_complete,
        }
