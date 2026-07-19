/**
 * Boot / health-gate / stop the REAL Omni engine sidecar for the live suite.
 *
 * This is the "real stack, never mock" contract of §4.9.8 made mechanical:
 * it seeds a real DB, launches `python -m engine.server`, waits for a real
 * /health 200, and — critically — HEALTH-GATES A REAL ask.query success
 * before any test or recording proceeds. If the real path is not green we
 * fail loud rather than record a broken product.
 */
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, openSync, closeSync, writeFileSync, readFileSync } from "node:fs";
import {
  ASK_PROBE_SCRIPT,
  DB_PATH,
  ENGINE_HTTP,
  ENGINE_LOG,
  ENGINE_PID_FILE,
  ENGINE_PORT,
  MIGRATIONS_DIR,
  MODELS_DIR,
  RUN_DIR,
  SEED_SCRIPT,
  VAULT_DIR,
  VENV_PYTHON,
  WORKTREE_ROOT,
  engineSpawnEnv,
} from "./e2e-env";

/** Two files whose mere presence satisfies setup.status's .is_file() model check.
 *  We never fake transcription — STT preload fails harmlessly on these (proven);
 *  they only unblock the UI's setup-complete gate so the main shell renders. */
const MODEL_FILES = ["silero_vad.onnx", "parakeet-tdt-0.6b-v2.nemo"];

export function killPort(port: number): void {
  // PowerShell is the reliable port-killer on this box (§7.1).
  spawnSync(
    "powershell.exe",
    [
      "-NoProfile",
      "-Command",
      `Get-NetTCPConnection -LocalPort ${port} -State Listen -ErrorAction SilentlyContinue | ` +
        `ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }`,
    ],
    { stdio: "ignore" },
  );
}

function runPython(scriptArgs: string[], label: string): void {
  const res = spawnSync(VENV_PYTHON, scriptArgs, {
    cwd: WORKTREE_ROOT,
    env: engineSpawnEnv(),
    encoding: "utf8",
  });
  if (res.status !== 0) {
    throw new Error(`E2E ${label} failed (exit ${res.status}):\n${res.stdout}\n${res.stderr}`);
  }
  // Seed prints counts only (no secrets) — surface it so the run is auditable.
  if (res.stdout.trim()) console.log(`[e2e:${label}] ${res.stdout.trim()}`);
}

export function seedDatabase(): void {
  mkdirSync(RUN_DIR, { recursive: true });
  mkdirSync(MODELS_DIR, { recursive: true });
  for (const f of MODEL_FILES) {
    const p = `${MODELS_DIR}/${f}`;
    if (!existsSync(p)) writeFileSync(p, "");
  }
  runPython(
    [SEED_SCRIPT, "--db", DB_PATH, "--vault", VAULT_DIR, "--migrations", MIGRATIONS_DIR],
    "seed",
  );
}

async function waitForHealth(timeoutMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let lastErr = "";
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${ENGINE_HTTP}/health`, { signal: AbortSignal.timeout(3000) });
      if (res.ok) return;
      lastErr = `status ${res.status}`;
    } catch (e) {
      lastErr = e instanceof Error ? e.message : String(e);
    }
    await new Promise((r) => setTimeout(r, 1500));
  }
  const log = existsSync(ENGINE_LOG) ? readFileSync(ENGINE_LOG, "utf8").slice(-2000) : "(no log)";
  throw new Error(`E2E: engine /health not ready in ${timeoutMs}ms (${lastErr}). Log tail:\n${log}`);
}

/** Health-gate a REAL ask.query success — never record against a broken stack. */
export function assertRealAskWorks(): void {
  if (process.env.OMNI_E2E_ALLOW_NO_KEYS === "1" && !process.env.GEMINI_API_KEY) {
    // Offline media/shell runs: capture UI against a real seeded engine without
    // inventing cloud answers. Specs that need Ask must still assert success.
    console.log("[e2e:ask-gate] skipped (OMNI_E2E_ALLOW_NO_KEYS=1, no GEMINI_API_KEY)");
    return;
  }
  const res = spawnSync(VENV_PYTHON, [ASK_PROBE_SCRIPT, "--url", `ws://127.0.0.1:${ENGINE_PORT}/ws`], {
    cwd: WORKTREE_ROOT,
    env: engineSpawnEnv(),
    encoding: "utf8",
  });
  console.log(`[e2e:ask-gate] ${res.stdout.trim()}`);
  if (res.status !== 0) {
    throw new Error(
      `E2E: REAL ask.query gate FAILED (exit ${res.status}). Refusing to proceed against a ` +
        `stack that cannot answer.\n${res.stdout}\n${res.stderr}`,
    );
  }
}

/** Is a healthy engine already listening on the pinned port? (reuse guard). */
async function isEngineHealthy(): Promise<boolean> {
  try {
    const res = await fetch(`${ENGINE_HTTP}/health`, { signal: AbortSignal.timeout(2000) });
    return res.ok;
  } catch {
    return false;
  }
}

export async function bootEngine(): Promise<void> {
  // Fast-iteration reuse: OMNI_E2E_REUSE_ENGINE=1 keeps one seeded engine up
  // across runs so we skip the ~2-min torch/nemo cold boot each time. Never on
  // CI (always a clean boot there) — this is a local developer convenience.
  if (process.env.OMNI_E2E_REUSE_ENGINE === "1" && !process.env.CI && (await isEngineHealthy())) {
    console.log("[e2e] reusing the already-healthy engine (OMNI_E2E_REUSE_ENGINE=1)");
    assertRealAskWorks();
    return;
  }
  killPort(ENGINE_PORT);
  seedDatabase();
  mkdirSync(RUN_DIR, { recursive: true });
  const logFd = openSync(ENGINE_LOG, "w");
  const child = spawn(VENV_PYTHON, ["-m", "engine.server"], {
    cwd: WORKTREE_ROOT,
    env: engineSpawnEnv(),
    stdio: ["ignore", logFd, logFd],
    detached: true,
  });
  child.unref();
  closeSync(logFd);
  if (child.pid) writeFileSync(ENGINE_PID_FILE, String(child.pid));
  // torch/nemo import is slow on cold start (~90s observed, §smoke); be generous.
  await waitForHealth(180_000);
  assertRealAskWorks();
}

export function stopEngine(): void {
  // Under the reuse guard we leave the engine up for the next run.
  if (process.env.OMNI_E2E_REUSE_ENGINE === "1" && !process.env.CI) {
    console.log("[e2e] leaving engine up for reuse (OMNI_E2E_REUSE_ENGINE=1)");
    return;
  }
  if (existsSync(ENGINE_PID_FILE)) {
    const pid = Number(readFileSync(ENGINE_PID_FILE, "utf8").trim());
    if (Number.isFinite(pid) && pid > 0) {
      spawnSync("powershell.exe", ["-NoProfile", "-Command", `Stop-Process -Id ${pid} -Force -ErrorAction SilentlyContinue`], { stdio: "ignore" });
    }
  }
  killPort(ENGINE_PORT);
}
