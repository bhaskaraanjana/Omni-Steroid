//! Omni desktop shell: builds the Tauri app, wires the tray, and supervises
//! the Python engine sidecar. The shell is deliberately thin — it never
//! touches audio, transcripts, or keys; that is the engine's job.
//!
//! Startup resilience (manual verification — the full Tauri setup hook cannot
//! be unit-tested in-process, so the guarantees are proven by inspection and
//! by the checks below rather than a fake test):
//!   1. Force a tray failure (e.g. return `Err` from `tray::build_tray`): the
//!      main window must still open — only a `warn!` is logged.
//!   2. Occupy the hold key with another app before launch, or set an invalid
//!      hotkey: the app must launch normally; dictation just won't fire.
//!   3. Rename/remove `uv`/the engine binary: the shell must launch; the
//!      supervisor logs "cannot start engine sidecar … retrying" and loops.
//!   4. Launch twice: the second instance focuses the first (single-instance)
//!      and never panics with "HotKey already registered" — the exit handler
//!      released the binding, and every bind unregisters first.
//!
//! The ONLY launch-fatal step is the main-window/context build (`.expect`
//! below): without it there is no app to fall back to.

// Injection modules are `pub` for the live integration test
// (tests/live_notepad_injection_roundtrip.rs) — the running app reaches them
// only through the `inject_dictation_text` command.
pub mod dictation_clipboard_win32;
pub mod dictation_hotkey_accelerator;
pub mod dictation_injection_win32;
mod captions_overlay_window;
mod capture_status_bar_window;
mod dictation_pill_window;
mod meeting_toast_window;
pub mod dictation_text_injection;
mod engine_sidecar;
#[cfg(windows)]
mod engine_sidecar_job_object_win32;
mod tray;
mod updater_launch_check;

use std::path::{Path, PathBuf};
use tauri::{AppHandle, Manager, RunEvent};

/// Validated reveal action — never pass a bare file path to explorer.exe.
#[derive(Debug, Clone, PartialEq, Eq)]
enum RevealAction {
    /// Open the directory in Explorer.
    OpenDirectory(PathBuf),
    /// Select the file in its parent folder (`explorer /select,<path>`).
    SelectFile(PathBuf),
}

/// Canonicalize, require existence, and decide open-dir vs select-file.
/// Fail-closed: anything that is not an existing file or directory is rejected.
fn prepare_reveal_path(path: &str) -> Result<RevealAction, String> {
    let raw = Path::new(path);
    // canonicalize fails for missing paths — fail closed.
    let canonical = raw
        .canonicalize()
        .map_err(|e| format!("path does not exist or cannot be resolved: {e}"))?;
    if canonical.is_dir() {
        return Ok(RevealAction::OpenDirectory(canonical));
    }
    if canonical.is_file() {
        return Ok(RevealAction::SelectFile(canonical));
    }
    Err("path is neither a file nor a directory".to_string())
}

/// Reveal a filesystem path in the OS file explorer. Best-effort UI
/// convenience only — never touches audio, transcripts, or keys. On failure
/// the caller falls back to copying the path to the clipboard.
///
/// Security: canonicalize + exist; directories open, files use `/select,` so a
/// compromised webview cannot launch an arbitrary `.exe`/`.bat` via explorer.
#[tauri::command]
fn reveal_path_in_explorer(path: String) -> Result<(), String> {
    let action = prepare_reveal_path(&path)?;

    #[cfg(target_os = "windows")]
    {
        let result = match action {
            RevealAction::OpenDirectory(dir) => std::process::Command::new("explorer")
                .arg(dir.as_os_str())
                .spawn(),
            RevealAction::SelectFile(file) => {
                // /select,<path> — no space after comma; bare file paths would
                // open by association (execute .exe/.bat) — never do that.
                let arg = format!("/select,{}", file.display());
                std::process::Command::new("explorer").arg(arg).spawn()
            }
        };
        return result.map(|_| ()).map_err(|e| e.to_string());
    }

    #[cfg(target_os = "macos")]
    {
        // `open -R` reveals a file in Finder; for dirs plain `open` is fine.
        let result = match action {
            RevealAction::OpenDirectory(dir) => {
                std::process::Command::new("open").arg(dir.as_os_str()).spawn()
            }
            RevealAction::SelectFile(file) => std::process::Command::new("open")
                .args(["-R"])
                .arg(file.as_os_str())
                .spawn(),
        };
        return result.map(|_| ()).map_err(|e| e.to_string());
    }

    #[cfg(all(unix, not(target_os = "macos")))]
    {
        let target = match action {
            RevealAction::OpenDirectory(p) => p,
            RevealAction::SelectFile(p) => p
                .parent()
                .map(|parent| parent.to_path_buf())
                .unwrap_or(p),
        };
        return std::process::Command::new("xdg-open")
            .arg(target.as_os_str())
            .spawn()
            .map(|_| ())
            .map_err(|e| e.to_string());
    }

    #[cfg(not(any(target_os = "windows", target_os = "macos", unix)))]
    {
        let _ = action;
        Err("reveal in explorer is not supported on this platform".to_string())
    }
}

/// Bring the main window to the foreground (used by the tray and by a second
/// app launch via the single-instance plugin).
fn focus_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        // Best-effort: a hidden/minimised window must still come forward.
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        // Single instance MUST be the first plugin so a second launch is
        // intercepted before any other state is created.
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            focus_main_window(app);
        }))
        .plugin(
            tauri_plugin_log::Builder::new()
                .level(log::LevelFilter::Info)
                .build(),
        )
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        // M7 onboarding: native folder picker for the vault step (open() only;
        // scoped to the main window by capabilities/onboarding.json).
        .plugin(tauri_plugin_dialog::init())
        // M7: auto-update from GitHub Releases (signature-verified) + the
        // process plugin backing the post-install relaunch.
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        // M5: the pill's paste command (clipboard-swap + SendInput Ctrl+V).
        // M7: updater commands driven from Settings.
        .invoke_handler(tauri::generate_handler![
            dictation_text_injection::inject_dictation_text,
            dictation_pill_window::set_dictation_hotkey,
            captions_overlay_window::set_captions_overlay_visible,
            capture_status_bar_window::set_capture_status_bar_visible,
            capture_status_bar_window::capture_status_bar_stop_capture,
            meeting_toast_window::set_meeting_toast_visible,
            meeting_toast_window::meeting_toast_start_capture,
            meeting_toast_window::meeting_toast_dismiss,
            meeting_toast_window::meeting_toast_stop_capture,
            meeting_toast_window::meeting_toast_keep_going,
            updater_launch_check::updater_download_and_install,
            updater_launch_check::updater_restart_app,
            reveal_path_in_explorer
        ])
        // STARTUP-RESILIENCE CONTRACT (verify manually per the module comment
        // below): EVERY subsystem started here is NON-FATAL. A failure in any
        // one of them logs a warning and lets the app continue to a visible,
        // usable window. Only the main-window/context build below (`.expect`)
        // is allowed to fail the launch, because without it there is no app.
        .setup(|app| {
            // Tracks the live hold-key binding; must exist before the pill
            // setup binds so a rebind/exit can find and drop it.
            app.manage(dictation_pill_window::DictationHotkey::default());
            // Non-fatal: the tray is the product's primary surface, but a tray
            // build failure (rare shell/icon error) must not panic startup —
            // the main window still opens. (Previously `?` here crashed the
            // whole app: the same bug class as the F9 hotkey crash.)
            if let Err(e) = tray::build_tray(app.handle()) {
                log::warn!("system tray setup skipped: {e}");
            }
            // M7: one update check per launch, release builds only (dev has
            // no published release to compare against — skip the noise).
            // Already non-fatal: it spawns async and reports offline as an
            // event, never an error that could reach this hook.
            if !cfg!(debug_assertions) {
                updater_launch_check::spawn_launch_check(app.handle());
            }
            // M5: hold-key dictation pill (window + global shortcut binding).
            // Non-fatal: dictation setup must never prevent Omni from
            // launching — log and continue on any failure.
            if let Err(e) = dictation_pill_window::setup_dictation_pill(app.handle()) {
                log::warn!("dictation pill setup skipped: {e}");
            }
            if let Err(e) = captions_overlay_window::setup_captions_overlay(app.handle()) {
                log::warn!("captions overlay setup skipped: {e}");
            }
            if let Err(e) = meeting_toast_window::setup_meeting_toast(app.handle()) {
                log::warn!("meeting toast setup skipped: {e}");
            }
            if let Err(e) = capture_status_bar_window::setup_capture_status_bar(app.handle()) {
                log::warn!("capture status bar setup skipped: {e}");
            }
            // Start supervising the engine sidecar immediately; the supervisor
            // tolerates the engine being absent (retry loop, never a crash)
            // and its own thread-spawn failure is non-fatal (see the module).
            let sidecar = engine_sidecar::EngineSidecar::spawn_supervised(app.handle().clone());
            app.manage(sidecar);
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Omni");

    app.run(|app_handle, event| {
        if let RunEvent::Exit = event {
            // Contract: never leave an orphaned engine process behind.
            app_handle
                .state::<engine_sidecar::EngineSidecar>()
                .shutdown();
            // Contract: release the global hold-key binding on the way out so a
            // stale shortcut can never outlive the process and collide with the
            // next launch (the "HotKey already registered" crash).
            dictation_pill_window::unregister_hold_shortcut(app_handle);
        }
    });
}

#[cfg(test)]
mod reveal_path_tests {
    use super::{prepare_reveal_path, RevealAction};
    use std::fs;

    #[test]
    fn rejects_missing_path() {
        let err = prepare_reveal_path("C:\\definitely\\missing\\omni-path-xyz")
            .expect_err("missing path must fail closed");
        assert!(err.contains("does not exist") || err.contains("cannot be resolved"));
    }

    #[test]
    fn opens_existing_directory() {
        let dir = std::env::temp_dir().join("omni_reveal_dir_test");
        let _ = fs::create_dir_all(&dir);
        let action = prepare_reveal_path(dir.to_str().expect("utf8 temp path"))
            .expect("existing dir must be accepted");
        match action {
            RevealAction::OpenDirectory(p) => {
                assert!(p.is_dir());
            }
            RevealAction::SelectFile(_) => panic!("directory must not use select"),
        }
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn selects_existing_file() {
        let file = std::env::temp_dir().join("omni_reveal_file_test.txt");
        fs::write(&file, b"ok").expect("write temp file");
        let action = prepare_reveal_path(file.to_str().expect("utf8 temp path"))
            .expect("existing file must be accepted");
        match action {
            RevealAction::SelectFile(p) => {
                assert!(p.is_file());
            }
            RevealAction::OpenDirectory(_) => panic!("file must not open as directory"),
        }
        let _ = fs::remove_file(&file);
    }
}
