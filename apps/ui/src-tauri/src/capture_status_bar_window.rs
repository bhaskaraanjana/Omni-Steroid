//! Desktop capture status bar: always-on-top frameless window at the
//! bottom-center of the primary monitor (first show). Loads
//! `capture-status-bar.html` (separate Vite entry). Visibility + content
//! are driven from the main window; Stop focuses main and emits an event.
//! User may drag the bar via the webview `data-tauri-drag-region`.

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager, PhysicalPosition, WebviewUrl, WebviewWindowBuilder};

/// Window label pinned by capabilities/capture-status-bar.json.
pub const CAPTURE_STATUS_BAR_WINDOW_LABEL: &str = "capture-status-bar";

const BAR_WIDTH: f64 = 420.0;
const BAR_HEIGHT: f64 = 72.0;
const BAR_BOTTOM_MARGIN: f64 = 28.0;

/// Content pushed from the main window so the overlay needs no engine socket.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CaptureStatusBarContent {
    pub status: String,
    pub elapsed_seconds: Option<u64>,
    pub title: Option<String>,
}

/// Create the (hidden) status bar window up front — first show must be instant.
pub fn setup_capture_status_bar(app: &AppHandle) -> tauri::Result<()> {
    if app.get_webview_window(CAPTURE_STATUS_BAR_WINDOW_LABEL).is_some() {
        return Ok(()); // idempotent (dev hot-restart safety)
    }
    WebviewWindowBuilder::new(
        app,
        CAPTURE_STATUS_BAR_WINDOW_LABEL,
        WebviewUrl::App("capture-status-bar.html".into()),
    )
    .title("Omni Steroid Capture")
    .inner_size(BAR_WIDTH, BAR_HEIGHT)
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

/// Bottom-center of the primary monitor, DPI-aware (matches captions overlay).
fn position_bottom_center(app: &AppHandle, window: &tauri::WebviewWindow) {
    // Explicit primary_monitor() — current_monitor() of a hidden window is unreliable.
    let Ok(Some(monitor)) = app.primary_monitor() else {
        return;
    };
    let scale = monitor.scale_factor();
    let monitor_size = monitor.size();
    let width = (BAR_WIDTH * scale) as i32;
    let height = (BAR_HEIGHT * scale) as i32;
    let x = monitor.position().x + (monitor_size.width as i32 - width) / 2;
    let y = monitor.position().y + monitor_size.height as i32
        - height
        - (BAR_BOTTOM_MARGIN * scale) as i32;
    let _ = window.set_position(PhysicalPosition::new(x, y));
}

fn focus_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

/// Show or hide the capture status bar. Repositions only when becoming visible
/// so a user drag is preserved across content updates (elapsed timer ticks).
#[tauri::command]
pub fn set_capture_status_bar_visible(
    app: AppHandle,
    visible: bool,
    content: Option<CaptureStatusBarContent>,
) -> tauri::Result<()> {
    let window = match app.get_webview_window(CAPTURE_STATUS_BAR_WINDOW_LABEL) {
        Some(w) => w,
        None => {
            setup_capture_status_bar(&app)?;
            app.get_webview_window(CAPTURE_STATUS_BAR_WINDOW_LABEL)
                .ok_or_else(|| tauri::Error::FailedToReceiveMessage)?
        }
    };
    if visible {
        if let Some(payload) = content {
            // Main window is the single source of truth — push content before show.
            let _ = window.emit("capture-status-bar-content", payload);
        }
        let becoming_visible = !window.is_visible().unwrap_or(false);
        if becoming_visible {
            position_bottom_center(&app, &window);
            window.show()?;
        }
    } else {
        window.hide()?;
    }
    Ok(())
}

/// User pressed Stop: hide bar, focus main, emit so main requests capture stop.
#[tauri::command]
pub fn capture_status_bar_stop_capture(app: AppHandle) -> tauri::Result<()> {
    set_capture_status_bar_visible(app.clone(), false, None)?;
    focus_main_window(&app);
    if let Some(main) = app.get_webview_window("main") {
        let _ = main.emit("capture-status-bar-stop-capture", ());
    }
    Ok(())
}
