//! Hold-to-dictate: global F9 hold -> frameless "pill" overlay window.
//!
//! Owns the M5 shell surface: registers the hold-key global shortcut,
//! creates the always-on-top transparent pill window (loads `pill.html`,
//! a separate Vite entry), positions it bottom-center of the current
//! monitor, and relays key state to it as Tauri events. Everything
//! intelligent (mic capture, STT, mode split) lives in the Python engine —
//! the pill webview talks to it over the same loopback WebSocket as the
//! main window.
//!
//! Event contract with `apps/ui/src/pill/`:
//! - `dictation-hold-pressed`  — key went down (pill shows + begins); its
//!   payload carries the KEYDOWN-captured foreground window (`target_hwnd`)
//!   and whether it is an external app (`inject_eligible`) — the injection
//!   target is decided at keydown, never at release (focus contract).
//! - `dictation-hold-released` — key came up (pill ends the session)
//! The pill window hides ITSELF once its result popover is dismissed. It
//! is created unfocused and never steals focus — the user keeps typing
//! wherever they were.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;

use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager, PhysicalPosition, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};

use crate::dictation_hotkey_accelerator::{accelerator_from_keys, DEFAULT_DICTATION_HOLD_KEY};

/// The currently-registered hold-key accelerator. Tracked in managed state so
/// a rebind can drop the previous binding first and app exit can release the
/// key — a stale, never-released binding is exactly what produced the
/// "HotKey already registered" crash on the next launch.
pub struct DictationHotkey(Mutex<String>);

impl Default for DictationHotkey {
    fn default() -> Self {
        Self(Mutex::new(DEFAULT_DICTATION_HOLD_KEY.to_string()))
    }
}

/// Window label the capability file and the pill webview both pin.
pub const PILL_WINDOW_LABEL: &str = "pill";

// Logical window size. The visible pill row is ~44px (design §07); the
// WINDOW is taller and fully transparent so the 320px-wide result popover
// (label + quote + title + buttons, ~200px) can rise below the pill
// without clipping. Nothing paints outside the pill/popover surfaces.
const PILL_WIDTH: f64 = 420.0;
const PILL_HEIGHT: f64 = 300.0;
const PILL_BOTTOM_MARGIN: f64 = 48.0;

// Event names mirrored in apps/ui/src/pill/dictation-engine-bridge.ts.
const EVENT_HOLD_PRESSED: &str = "dictation-hold-pressed";
const EVENT_HOLD_RELEASED: &str = "dictation-hold-released";

/// Windows key auto-repeat fires repeated Pressed events while F9 is held;
/// only the FIRST press may show the pill and start a session.
static HOLD_ACTIVE: AtomicBool = AtomicBool::new(false);

/// Payload of `dictation-hold-pressed` (mirrored fail-closed by
/// `parseHoldPressedPayload` in dictation-engine-bridge.ts).
#[derive(Clone, Serialize)]
struct HoldPressedPayload {
    /// True when an EXTERNAL app owned focus at keydown — the default
    /// disposition is then INJECT (paste into that app on release).
    inject_eligible: bool,
    /// The keydown foreground window, as an integer handle for the bridge.
    target_hwnd: i64,
}

/// Snapshot the foreground window AT KEYDOWN. Eligible only when it is a
/// real window that is not one of Omni's own (dictating into Omni's main
/// window stays on the note path — deny by default).
fn capture_injection_target(app: &AppHandle) -> HoldPressedPayload {
    #[cfg(windows)]
    {
        // SAFETY: reading the foreground window has no preconditions.
        let foreground =
            unsafe { windows_sys::Win32::UI::WindowsAndMessaging::GetForegroundWindow() };
        if foreground == 0 {
            return HoldPressedPayload { inject_eligible: false, target_hwnd: 0 };
        }
        let ours = app.webview_windows().values().any(|window| {
            window
                .hwnd()
                .map(|handle| handle.0 as isize == foreground)
                .unwrap_or(false)
        });
        return HoldPressedPayload {
            inject_eligible: !ours,
            target_hwnd: foreground as i64,
        };
    }
    #[cfg(not(windows))]
    {
        let _ = app; // injection is Windows-only; note mode everywhere else
        HoldPressedPayload { inject_eligible: false, target_hwnd: 0 }
    }
}

/// Create the (hidden) pill window and bind the hold shortcut.
/// Called once from the app `setup` hook.
pub fn setup_dictation_pill(app: &AppHandle) -> tauri::Result<()> {
    create_pill_window(app)?;
    // Bind the DEFAULT key at startup; the UI pushes the user's configured key
    // moments later via `set_dictation_hotkey` (it reads the engine setting on
    // boot), so a rebind takes effect on the same launch, not just the next.
    // Non-fatal: a hotkey conflict must NEVER stop Omni from launching.
    if let Err(e) = bind_hold_shortcut(app, DEFAULT_DICTATION_HOLD_KEY) {
        log::warn!("dictation hold key '{DEFAULT_DICTATION_HOLD_KEY}' not registered: {e}");
    }
    Ok(())
}

/// Build the pill window up front, hidden — the first keypress must show
/// it instantly, not pay webview cold-start latency.
fn create_pill_window(app: &AppHandle) -> tauri::Result<()> {
    if app.get_webview_window(PILL_WINDOW_LABEL).is_some() {
        return Ok(()); // idempotent (dev hot-restart safety)
    }
    WebviewWindowBuilder::new(app, PILL_WINDOW_LABEL, WebviewUrl::App("pill.html".into()))
        .title("Omni Steroid Dictation")
        .inner_size(PILL_WIDTH, PILL_HEIGHT)
        .decorations(false)
        .transparent(true)
        // Windows: native shadow on undecorated windows draws a 1px white
        // frame around the whole transparent bounds — the "weird border".
        // Elevation comes from CSS --shadow-float on the pill/popover.
        .shadow(false)
        .always_on_top(true)
        .skip_taskbar(true)
        .resizable(false)
        .maximizable(false)
        .minimizable(false)
        .visible(false)
        // Never steal focus: the user is dictating over whatever app they
        // are in; the engine owns the mic, the pill only displays state.
        .focused(false)
        .build()?;
    Ok(())
}

/// (Re)bind the global hold shortcut to `accelerator`, dropping whatever was
/// bound before so registration is idempotent and can never trip "already
/// registered" on a rebind or a dev hot-restart. Returns the tauri result so
/// the Settings command can surface a rebind failure to the user; startup
/// treats a failure as non-fatal (logs and continues).
fn bind_hold_shortcut(
    app: &AppHandle,
    accelerator: &str,
) -> Result<(), tauri_plugin_global_shortcut::Error> {
    let shortcuts = app.global_shortcut();
    // Drop the previously-tracked binding, then the target itself (a stale
    // prior instance can still own the key at the OS level) — idempotent.
    if let Some(state) = app.try_state::<DictationHotkey>() {
        if let Ok(previous) = state.0.lock() {
            let _ = shortcuts.unregister(previous.as_str());
        }
    }
    let _ = shortcuts.unregister(accelerator);
    shortcuts.on_shortcut(accelerator, |app, _shortcut, event| {
        handle_hold_event(app, event.state());
    })?;
    // Record the live binding only after a successful register.
    if let Some(state) = app.try_state::<DictationHotkey>() {
        if let Ok(mut current) = state.0.lock() {
            *current = accelerator.to_string();
        }
    }
    Ok(())
}

/// Shared Pressed/Released body. Repeat-guarded: Windows key auto-repeat fires
/// repeated Pressed events while the key is held, but only the first may start
/// a session; only a real release ends one.
fn handle_hold_event(app: &AppHandle, state: ShortcutState) {
    match state {
        ShortcutState::Pressed => {
            // Auto-repeat guard: only the leading edge starts a session.
            if claim_press(&HOLD_ACTIVE) {
                // Capture the target BEFORE showing the pill: the pill is
                // unfocused, but the order still guarantees the user's window
                // is what gets snapshotted.
                let payload = capture_injection_target(app);
                show_pill_and_emit(app, EVENT_HOLD_PRESSED, payload);
            }
        }
        ShortcutState::Released => {
            if claim_release(&HOLD_ACTIVE) {
                emit_to_pill(app, EVENT_HOLD_RELEASED);
            }
        }
    }
}

/// Leading-edge guard: `true` only on the FIRST Pressed of a hold (Windows key
/// auto-repeat delivers many while the key is down). Pure over the passed flag
/// so the repeat-guard is unit-testable without a live shortcut / AppHandle.
fn claim_press(active: &AtomicBool) -> bool {
    !active.swap(true, Ordering::SeqCst)
}

/// Trailing-edge guard: `true` only on the release that actually ends an active
/// hold — a stray Released with no matching press must not emit.
fn claim_release(active: &AtomicBool) -> bool {
    active.swap(false, Ordering::SeqCst)
}

/// Settings-driven rebind: the UI pushes the configured push-to-talk key (the
/// recorded token list) on boot and whenever the user changes it, so a user
/// whose default key is taken can rebind it in Settings and have it take
/// effect live — no restart needed.
#[tauri::command]
pub fn set_dictation_hotkey(app: AppHandle, keys: Vec<String>) -> Result<(), String> {
    let accelerator = accelerator_from_keys(&keys);
    bind_hold_shortcut(&app, &accelerator).map_err(|error| error.to_string())
}

/// Release the hold-key binding on app exit so a stale global shortcut can
/// never outlive the process and block the next launch (the original crash).
pub fn unregister_hold_shortcut(app: &AppHandle) {
    if let Some(state) = app.try_state::<DictationHotkey>() {
        if let Ok(current) = state.0.lock() {
            // Best-effort: releasing the OS-level binding on the way out.
            let _ = app.global_shortcut().unregister(current.as_str());
        }
    }
}

fn show_pill_and_emit(app: &AppHandle, event: &str, payload: HoldPressedPayload) {
    if let Some(window) = app.get_webview_window(PILL_WINDOW_LABEL) {
        position_bottom_center(&window);
        // Best-effort: a failed show must not poison the shortcut handler —
        // the engine session is driven by the events, not by visibility.
        let _ = window.show();
        let _ = window.emit(event, payload);
    }
}

fn emit_to_pill(app: &AppHandle, event: &str) {
    if let Some(window) = app.get_webview_window(PILL_WINDOW_LABEL) {
        let _ = window.emit(event, ());
    }
}

/// Bottom-center of the pill's current monitor, DPI-aware.
fn position_bottom_center(window: &tauri::WebviewWindow) {
    let Ok(Some(monitor)) = window.current_monitor() else {
        return; // no monitor info: keep whatever position we have
    };
    let scale = monitor.scale_factor();
    let monitor_size = monitor.size();
    let width = (PILL_WIDTH * scale) as i32;
    let height = (PILL_HEIGHT * scale) as i32;
    let x = monitor.position().x + (monitor_size.width as i32 - width) / 2;
    let y = monitor.position().y + monitor_size.height as i32
        - height
        - (PILL_BOTTOM_MARGIN * scale) as i32;
    let _ = window.set_position(PhysicalPosition::new(x, y));
}

#[cfg(test)]
mod tests {
    use super::{claim_press, claim_release};
    use std::sync::atomic::AtomicBool;

    #[test]
    fn only_the_first_press_of_a_hold_starts_a_session() {
        let active = AtomicBool::new(false);
        // Leading edge fires once; every auto-repeat Pressed after it is ignored.
        assert!(claim_press(&active), "first press must start the session");
        assert!(!claim_press(&active), "auto-repeat press must be ignored");
        assert!(!claim_press(&active), "still held: no new session");
    }

    #[test]
    fn release_ends_an_active_hold_exactly_once() {
        let active = AtomicBool::new(false);
        claim_press(&active); // start a session
        assert!(claim_release(&active), "the matching release must end it");
        assert!(!claim_release(&active), "a second release must not re-fire");
    }

    #[test]
    fn a_stray_release_without_a_press_never_fires() {
        // Defends the ordering invariant: a Released with no active hold (e.g.
        // a shortcut re-bind mid-hold) must not emit a phantom end event.
        let active = AtomicBool::new(false);
        assert!(!claim_release(&active));
    }

    #[test]
    fn press_release_cycles_are_independent() {
        let active = AtomicBool::new(false);
        for _ in 0..3 {
            assert!(claim_press(&active));
            assert!(!claim_press(&active));
            assert!(claim_release(&active));
            assert!(!claim_release(&active));
        }
    }
}
