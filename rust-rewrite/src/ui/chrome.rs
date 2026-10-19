//! Windows window chrome for the FreeDictate window, ported from
//! src/freedictate/ui/native.py: dark or palette-tinted title bar, rounded
//! corners and the Mica/Acrylic system backdrop, applied to the winit window
//! through DWM attributes.
//!
//! iced does not hand out the HWND, so `request` finds the window by its
//! unique title and applies the attributes there. It is called once at boot
//! (the window may not exist for a moment, hence the retry) and again
//! whenever the theme changes while the window is live.

use std::time::Duration;

use crate::ui::theme::Palette;

const WINDOW_TITLE: &str = "FreeDictate";
/// How long request() keeps looking for the window before giving up: long
/// enough for a cold start with the model loading, short enough to not leak
/// a thread forever if the window never opens.
const RETRY_SECONDS: u64 = 20;

/// Apply palette + backdrop chrome to the FreeDictate window. Fire and
/// forget: a background thread finds the window and applies the attributes.
/// Safe to call repeatedly (theme change, backdrop change).
pub fn request(palette: Palette, backdrop: String) {
    std::thread::spawn(move || {
        let deadline = std::time::Instant::now() + Duration::from_secs(RETRY_SECONDS);
        loop {
            if let Some(hwnd) = find_window() {
                unsafe {
                    apply(hwnd, &palette, &backdrop);
                }
                return;
            }
            if std::time::Instant::now() >= deadline {
                return;
            }
            std::thread::sleep(Duration::from_millis(200));
        }
    });
}

/// The HWND of the FreeDictate window, found by exact title. The tray menu
/// and the app itself are the only windows with that name.
fn find_window() -> Option<windows::Win32::Foundation::HWND> {
    use windows::Win32::UI::WindowsAndMessaging::FindWindowW;
    let title: Vec<u16> = WINDOW_TITLE
        .encode_utf16()
        .chain(std::iter::once(0))
        .collect();
    let hwnd = unsafe { FindWindowW(windows::core::PCWSTR::null(), windows::core::PCWSTR(title.as_ptr())) };
    match hwnd {
        Ok(hwnd) if !hwnd.0.is_null() => Some(hwnd),
        _ => None,
    }
}

unsafe fn apply(hwnd: windows::Win32::Foundation::HWND, palette: &Palette, backdrop: &str) {
    use windows::Win32::Foundation::COLORREF;
    use windows::Win32::Graphics::Dwm::{
        DwmSetWindowAttribute, DWMWA_BORDER_COLOR, DWMWA_CAPTION_COLOR, DWMWA_SYSTEMBACKDROP_TYPE,
        DWMWA_TEXT_COLOR, DWMWA_USE_IMMERSIVE_DARK_MODE, DWMWA_WINDOW_CORNER_PREFERENCE,
        DWMWCP_ROUND, DWMSBT_MAINWINDOW, DWMSBT_NONE, DWMSBT_TABBEDWINDOW,
        DWMSBT_TRANSIENTWINDOW, DWMWINDOWATTRIBUTE,
    };

    fn set<T>(hwnd: windows::Win32::Foundation::HWND, attr: DWMWINDOWATTRIBUTE, value: &T) {
        unsafe {
            let _ = DwmSetWindowAttribute(
                hwnd,
                attr,
                <*const T>::cast(value),
                std::mem::size_of_val(value) as u32,
            );
        }
    }

    // Dark chrome flag first: with a backdrop on, Windows 11 blends the
    // material with the window tone, so this must match the palette before
    // the backdrop type is set.
    set(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, &palette.dark);

    // The system backdrop: mica, mica_alt (tabbed), acrylic or none. The
    // caption area is left transparent when a material is active so it reads
    // through; without one the caption is painted in the palette background
    // with palette text, which is the Fluent look of the Python title bar.
    let backdrop_kind = match backdrop {
        "mica" => DWMSBT_MAINWINDOW,
        "mica_alt" => DWMSBT_TABBEDWINDOW,
        "acrylic" => DWMSBT_TRANSIENTWINDOW,
        _ => DWMSBT_NONE,
    };
    set(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, &backdrop_kind);
    if backdrop_kind == DWMSBT_NONE {
        let caption = COLORREF(bgr(palette.bg));
        set(hwnd, DWMWA_CAPTION_COLOR, &caption);
    } else {
        let none = COLORREF(0xff_ff_ff_fe);
        set(hwnd, DWMWA_CAPTION_COLOR, &none);
    }
    let text = COLORREF(bgr(palette.text));
    set(hwnd, DWMWA_TEXT_COLOR, &text);

    // A hairline border in the accent, like the Python frame highlight, and
    // the standard Win11 rounded corners.
    let border = COLORREF(bgr(palette.accent));
    set(hwnd, DWMWA_BORDER_COLOR, &border);
    set(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, &DWMWCP_ROUND);
}

/// Win32 COLORREF is 0x00BBGGRR.
fn bgr(c: iced::Color) -> u32 {
    let (r, g, b) = (
        (c.r * 255.0).round() as u32,
        (c.g * 255.0).round() as u32,
        (c.b * 255.0).round() as u32,
    );
    (r & 0xff) | ((g & 0xff) << 8) | ((b & 0xff) << 16)
}
