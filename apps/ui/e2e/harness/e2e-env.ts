/**
 * Shared paths + environment for the live E2E harness.
 *
 * One place resolves every machine-specific path (the engine venv, the .env
 * that holds the provider keys, the run directory) so global-setup, teardown,
 * and the specs never re-derive them. Overridable via env vars for CI/other
 * machines; the defaults target this Windows dev box (§7.1).
 *
 * SECURITY: this module reads provider keys from the .env into the engine's
 * spawn environment only. It never logs a key value and never writes one to
 * disk — the engine reads them from its process env (key-store env fallback).
 */
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url)); // apps/ui/e2e/harness
export const E2E_DIR = path.resolve(here, ".."); // apps/ui/e2e
export const UI_DIR = path.resolve(E2E_DIR, ".."); // apps/ui
export const WORKTREE_ROOT = path.resolve(UI_DIR, "..", ".."); // repo/worktree root

/** The engine binds loopback-only on a pinned port; the UI hardcodes 8765. */
export const ENGINE_PORT = 8765;
export const ENGINE_HTTP = `http://127.0.0.1:${ENGINE_PORT}`;
export const ENGINE_WS = `ws://127.0.0.1:${ENGINE_PORT}/ws`;
/** Vite preview (production build) serves the REAL frontend here. */
export const PREVIEW_PORT = 4173;
export const BASE_URL = `http://127.0.0.1:${PREVIEW_PORT}`;

export const RUN_DIR = process.env.OMNI_E2E_RUN_DIR ?? path.join(WORKTREE_ROOT, ".e2e-run");
export const DB_PATH = path.join(RUN_DIR, "omni.db");
export const MODELS_DIR = path.join(RUN_DIR, "models");
export const VIDEO_DIR = path.join(RUN_DIR, "videos");
export const ENGINE_LOG = path.join(RUN_DIR, "engine.log");
export const ENGINE_PID_FILE = path.join(RUN_DIR, "engine.pid");
export const VAULT_DIR = path.join(E2E_DIR, "fixtures", "vault");
export const MIGRATIONS_DIR = path.join(WORKTREE_ROOT, "migrations");
/** Committed media outputs (feed README / landing / evidence lanes). */
export const MEDIA_DIR = path.join(WORKTREE_ROOT, "media");
export const SCREENSHOTS_DIR = path.join(MEDIA_DIR, "screenshots");

/** The engine runs on the checkout's venv (worktrees share no venv). */
export const VENV_PYTHON =
  process.env.OMNI_VENV_PYTHON ??
  path.join(WORKTREE_ROOT, ".venv", "Scripts", "python.exe");
/**
 * Optional provider keys file (gitignored). When absent, the engine still
 * boots offline; Ask synthesis needs GEMINI_API_KEY in env or DPAPI store.
 */
export const ENV_FILE =
  process.env.OMNI_ENV_FILE ?? path.join(WORKTREE_ROOT, ".env");

export const HARNESS_DIR = here;
export const SEED_SCRIPT = path.join(here, "seed_engine.py");
export const ASK_PROBE_SCRIPT = path.join(here, "ask_probe.py");

/** Only the keys the engine needs; parsed WITHOUT ever printing a value. */
const KEY_NAMES = [
  "GEMINI_API_KEY",
  "GROQ_API_KEY",
  "ANTHROPIC_API_KEY",
] as const;

/**
 * Parse provider keys from the .env file (values never logged).
 * Also accepts keys already present in the process environment.
 * Missing GEMINI is allowed when OMNI_E2E_ALLOW_NO_KEYS=1 (offline media /
 * shell-only runs); the ask health-gate then skips instead of inventing answers.
 */
export function loadProviderKeys(): Record<string, string> {
  const out: Record<string, string> = {};
  for (const name of KEY_NAMES) {
    const fromEnv = process.env[name]?.trim();
    if (fromEnv) out[name] = fromEnv;
  }
  if (existsSync(ENV_FILE)) {
    const text = readFileSync(ENV_FILE, "utf8");
    for (const line of text.split(/\r?\n/)) {
      const m = /^([A-Z0-9_]+)\s*=\s*(.*)$/.exec(line.trim());
      if (m === null) continue;
      const name = m[1];
      if (!(KEY_NAMES as readonly string[]).includes(name as (typeof KEY_NAMES)[number])) continue;
      let value = m[2].trim();
      if (
        (value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))
      ) {
        value = value.slice(1, -1);
      }
      if (value.length > 0) out[name] = value;
    }
  }
  if (!out["GEMINI_API_KEY"] && process.env.OMNI_E2E_ALLOW_NO_KEYS !== "1") {
    // ask_synthesis routes to Gemini — without it a REAL ask.query is impossible.
    throw new Error(
      `E2E: GEMINI_API_KEY missing (env or ${ENV_FILE}). Set OMNI_E2E_ALLOW_NO_KEYS=1 for offline shell/media capture.`,
    );
  }
  return out;
}

/** The full env for spawning the real engine (keys + OMNI_* + UTF-8, §7.1). */
export function engineSpawnEnv(): NodeJS.ProcessEnv {
  return {
    ...process.env,
    ...loadProviderKeys(),
    OMNI_ENGINE_PORT: String(ENGINE_PORT),
    OMNI_DB_PATH: DB_PATH,
    OMNI_VAULT_DIR: VAULT_DIR,
    OMNI_MODELS_DIR: MODELS_DIR,
    PYTHONPATH: WORKTREE_ROOT,
    PYTHONUTF8: "1",
    PYTHONIOENCODING: "utf-8",
  };
}
