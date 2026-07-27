//! Desktop meeting-detected toast: always-on-top frameless window at the
//! bottom-right of the primary monitor. Loads `meeting-toast.html` (separate
//! Vite entry). Visibility + content are driven from the main window; Start /
//! Not now / Stop / Keep going come back as shell commands that focus the main
//! window and emit events.

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager, PhysicalPosition, WebviewUrl, WebviewWindowBuilder};

/// Window label pinned by capabilities/meeting-toast.json.
pub const MEETING_TOAST_WINDOW_LABEL: &str = "meeting-toast";

const TOAST_WIDTH: f64 = 380.0;
const TOAST_HEIGHT: f64 = 168.0;
const TOAST_RIGHT_MARGIN: f64 = 24.0;
const TOAST_BOTTOM_MARGIN: f64 = 28.0;

/// Content pushed from the main window so the overlay needs no engine socket.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MeetingToastContent {
    pub suggestion: Option<MeetingToastSuggestion>,
    pub stop_hint_reason: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MeetingToastSuggestion {
    pub source: String,
    pub reason: String,
    pub confidence: f64,
    pub dedupe_key: Option<String>,
    pub auto_start: bool,
}

/// Create the (hidden) toast window up front — first show must be instant.
pub fn setup_meeting_toast(app: &AppHandle) -> tauri::Result<()> {
    if app.get_webview_window(MEETING_TOAST_WINDOW_LABEL).is_some() {
        return Ok(()); // idempotent (dev hot-restart safety)
    }
    WebviewWindowBuilder::new(
        app,
        MEETING_TOAST_WINDOW_LABEL,
        WebviewUrl::App("meeting-toast.html".into()),
    )
    .title("Omni Steroid Meeting")
    .inner_size(TOAST_WIDTH, TOAST_HEIGHT)
    .decorations(false)
    .transparent(true)
    // Windows: native shadow on undecorated windows = 1px white frame.
    .shadow(false)
    .always_on_top(true)
    .skip_taskbar(true)
    .resizable(false)
    .maximizable(false)
    .minimizable(false)
    .visible(false)
    .focused(false)
    .build()?;
    Ok(())
}

/// Bottom-right of the primary monitor, DPI-aware (matches dictation pill math).
fn position_bottom_right(app: &AppHandle, window: &tauri::WebviewWindow) {
    // Explicit primary_monitor() — current_monitor() of a hidden window is unreliable.
    let Ok(Some(monitor)) = app.primary_monitor() else {
        return;
    };
    let scale = monitor.scale_factor();
    let monitor_size = monitor.size();
    let width = (TOAST_WIDTH * scale) as i32;
    let height = (TOAST_HEIGHT * scale) as i32;
    let x = monitor.position().x + monitor_size.width as i32
        - width
        - (TOAST_RIGHT_MARGIN * scale) as i32;
    let y = monitor.position().y + monitor_size.height as i32
        - height
        - (TOAST_BOTTOM_MARGIN * scale) as i32;
    let _ = window.set_position(PhysicalPosition::new(x, y));
}

fn focus_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

/// Show or hide the desktop meeting toast. Repositions on show and pushes content.
#[tauri::command]
pub fn set_meeting_toast_visible(
    app: AppHandle,
    visible: bool,
    content: Option<MeetingToastContent>,
) -> tauri::Result<()> {
    let window = match app.get_webview_window(MEETING_TOAST_WINDOW_LABEL) {
        Some(w) => w,
        None => {
            setup_meeting_toast(&app)?;
            app.get_webview_window(MEETING_TOAST_WINDOW_LABEL)
                .ok_or_else(|| tauri::Error::FailedToReceiveMessage)?
        }
    };
    if visible {
        if let Some(payload) = content {
            // Main window is the single source of truth — push content before show.
            let _ = window.emit("meeting-toast-content", payload);
        }
        position_bottom_right(&app, &window);
        window.show()?;
        // Buttons need focus; steal briefly so Start / Not now work over Zoom.
        let _ = window.set_focus();
    } else {
        window.hide()?;
    }
    Ok(())
}

/// User accepted: hide toast, focus main, emit start so main navigates + captures.
#[tauri::command]
pub fn meeting_toast_start_capture(app: AppHandle, title: Option<String>) -> tauri::Result<()> {
    set_meeting_toast_visible(app.clone(), false, None)?;
    focus_main_window(&app);
    if let Some(main) = app.get_webview_window("main") {
        let _ = main.emit("meeting-toast-start-capture", title);
    }
    Ok(())
}

/// User declined: hide toast, tell main to dismiss (engine cooldown + store clear).
#[tauri::command]
pub fn meeting_toast_dismiss(app: AppHandle) -> tauri::Result<()> {
    set_meeting_toast_visible(app.clone(), false, None)?;
    if let Some(main) = app.get_webview_window("main") {
        let _ = main.emit("meeting-toast-dismiss", ());
    }
    Ok(())
}

/// User accepted the stop hint while capturing.
#[tauri::command]
pub fn meeting_toast_stop_capture(app: AppHandle) -> tauri::Result<()> {
    set_meeting_toast_visible(app.clone(), false, None)?;
    if let Some(main) = app.get_webview_window("main") {
        let _ = main.emit("meeting-toast-stop-capture", ());
    }
    Ok(())
}

/// User dismissed the stop hint ("Keep going"): hide toast and clear main stopHint.
#[tauri::command]
pub fn meeting_toast_keep_going(app: AppHandle) -> tauri::Result<()> {
    set_meeting_toast_visible(app.clone(), false, None)?;
    if let Some(main) = app.get_webview_window("main") {
        let _ = main.emit("meeting-toast-keep-going", ());
    }
    Ok(())
}
