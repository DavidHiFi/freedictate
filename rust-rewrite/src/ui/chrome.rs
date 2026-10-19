//! Windows window chrome for the FreeDictate window, ported from
//! src/freedictate/ui/native.py: dark or palette-tinted title bar, rounded
//! corners and the Mica/Acrylic system backdrop, applied to the winit window
//! through DWM attributes.
//!
//! iced does not hand out the HWND, so `request` finds the window by its
//! unique title and applies the attributes there. It is called once at boot
//! (the window may not exist for a moment, hence the retry) and again
//! whenever the theme changes while the window is live.
//!
//! Ported semantics (native.py): DWMWA_SYSTEMBACKDROP_TYPE needs Windows 11
//! 22H2 (build 22621); a material active in a window that keeps the native
//! title bar extends the frame with -1 margins ("sheet of glass") so the
//! material runs under the caption; "blur" is an accent, not a backdrop, and
//! the two must not stack, so the backdrop type is set to none first.

use std::time::Duration;

use windows::Win32::Foundation::HWND;

use crate::ui::theme::Palette;

const WINDOW_TITLE: &str = "FreeDictate";
/// How long request() keeps looking for the window before giving up: long
/// enough for a cold start with the model loading, short enough to not leak
/// a thread forever if the window never opens.
const RETRY_SECONDS: u64 = 20;

/// True when the named backdrop draws a see-through material, so the app
/// should leave its background clear (the caller picks the theme variant).
pub fn material_active(backdrop: &str) -> bool {
    matches!(backdrop, "mica" | "mica_alt" | "acrylic" | "blur")
}

/// The FreeDictate window's position and size in logical pixels, for the
/// window_geometry config value. Physical coordinates from GetWindowRect are
/// scaled down by the window's own DPI, so a value saved at one display
/// scale restores correctly at another. None when the window is not up.
pub fn current_geometry() -> Option<(i32, i32, u32, u32)> {
    use windows::Win32::UI::HiDpi::GetDpiForWindow;
    use windows::Win32::UI::WindowsAndMessaging::GetWindowRect;
    let hwnd = find_window()?;
    let mut rect = Default::default();
    if unsafe { GetWindowRect(hwnd, &mut rect) }.is_err() {
        return None;
    }
    let dpi = unsafe { GetDpiForWindow(hwnd) }.max(96);
    let scale = 96.0 / dpi as f32;
    let (l, t, r, b) = (rect.left as f32, rect.top as f32, rect.right as f32, rect.bottom as f32);
    // The outer rect round-trips as-is: saving and restoring the same
    // numbers through winit's logical size lands the window back where it
    // was, frame included.
    let (x, y) = (l * scale, t * scale);
    let (w, h) = ((r - l) * scale, (b - t) * scale);
    Some((x.round() as i32, y.round() as i32, w.round() as u32, h.round() as u32))
}

/// Parse the "x,y,w,h" geometry string. The Python app stores a Qt base64
/// blob under the same key, so anything without three commas parses as None
/// and the window falls back to the default size.
pub fn parse_geometry(raw: &str) -> Option<(i32, i32, u32, u32)> {
    let parts: Vec<&str> = raw.split(',').map(str::trim).collect();
    if parts.len() != 4 {
        return None;
    }
    let (x, y) = (parts[0].parse::<i32>().ok()?, parts[1].parse::<i32>().ok()?);
    let (w, h) = (parts[2].parse::<u32>().ok()?, parts[3].parse::<u32>().ok()?);
    // Reject absurd values (off-screen typos, a maximized-ish 0).
    if (w < 240 || w > 8192) || (h < 160 || h > 8192) {
        return None;
    }
    Some((x, y, w, h))
}

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
fn find_window() -> Option<HWND> {
    use windows::Win32::UI::WindowsAndMessaging::FindWindowW;
    let title: Vec<u16> = WINDOW_TITLE
        .encode_utf16()
        .chain(std::iter::once(0))
        .collect();
    let hwnd =
        unsafe { FindWindowW(windows::core::PCWSTR::null(), windows::core::PCWSTR(title.as_ptr())) };
    match hwnd {
        Ok(hwnd) if !hwnd.0.is_null() => Some(hwnd),
        _ => None,
    }
}

/// The Windows build number, from the registry like native.py's BUILD
/// (sys.getwindowsversion().build). 0 when unreadable — treated as too old.
fn windows_build() -> u32 {
    use windows::Win32::System::Registry::{
        RegCloseKey, RegOpenKeyExW, RegQueryValueExW, HKEY, HKEY_LOCAL_MACHINE, KEY_READ,
        REG_VALUE_TYPE,
    };
    unsafe {
        let mut key = HKEY::default();
        let path: Vec<u16> =
            "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\0".encode_utf16().collect();
        if RegOpenKeyExW(HKEY_LOCAL_MACHINE, windows::core::PCWSTR(path.as_ptr()), None, KEY_READ, &mut key)
            .is_err()
        {
            return 0;
        }
        let mut buffer = [0u16; 32];
        let mut size = (buffer.len() * std::mem::size_of::<u16>()) as u32;
        let mut kind = REG_VALUE_TYPE::default();
        let read = RegQueryValueExW(
            key,
            windows::core::w!("CurrentBuildNumber"),
            None,
            Some(&mut kind),
            Some(buffer.as_mut_ptr() as *mut u8),
            Some(&mut size),
        );
        let _ = RegCloseKey(key);
        if read.is_err() {
            return 0;
        }
        let len = buffer.iter().position(|&c| c == 0).unwrap_or(buffer.len());
        String::from_utf16_lossy(&buffer[..len]).trim().parse().unwrap_or(0)
    }
}

/// The accent policy + composition attribute data for the blur-behind
/// effect, laid out exactly as native.py's _ACCENT_POLICY.
#[repr(C)]
struct AccentPolicy {
    state: i32,
    flags: i32,
    gradient: u32,
    animation: i32,
}

#[repr(C)]
struct WindowCompositionAttributeData {
    attribute: i32,
    data: *const AccentPolicy,
    size: usize,
}

const WCA_ACCENT_POLICY: i32 = 19;
const ACCENT_BLUR_BEHIND: i32 = 3;

unsafe fn set_accent_blur_behind(hwnd: HWND) {
    // SetWindowCompositionAttribute is a private user32 export: it is not in
    // user32.lib, so it resolves through GetProcAddress instead of a link.
    #[link(name = "kernel32")]
    extern "system" {
        fn LoadLibraryW(name: *const u16) -> *mut core::ffi::c_void;
        fn GetProcAddress(
            module: *mut core::ffi::c_void,
            name: *const core::ffi::c_char,
        ) -> *mut core::ffi::c_void;
    }
    type SetCompositionAttr =
        unsafe extern "system" fn(HWND, *const WindowCompositionAttributeData) -> i32;

    let user32 = LoadLibraryW(windows::core::w!("user32").as_ptr());
    if user32.is_null() {
        return;
    }
    let entry = GetProcAddress(user32, c"SetWindowCompositionAttribute".as_ptr());
    if entry.is_null() {
        return;
    }
    let set_attr: SetCompositionAttr = core::mem::transmute(entry);

    let policy = AccentPolicy {
        state: ACCENT_BLUR_BEHIND,
        flags: 0,
        gradient: 0,
        animation: 0,
    };
    let data = WindowCompositionAttributeData {
        attribute: WCA_ACCENT_POLICY,
        data: &policy,
        size: std::mem::size_of::<AccentPolicy>(),
    };
    set_attr(hwnd, &data);
}

/// Sheet-of-glass frame extension, so the material runs under the caption of
/// a window that keeps the native title bar (native.py MARGINS(-1)).
unsafe fn extend_frame(hwnd: HWND, margins: i32) {
    use windows::Win32::Graphics::Dwm::{DwmExtendFrameIntoClientArea};
    let margins = windows::Win32::UI::Controls::MARGINS {
        cxLeftWidth: margins,
        cxRightWidth: margins,
        cyTopHeight: margins,
        cyBottomHeight: margins,
    };
    let _ = DwmExtendFrameIntoClientArea(hwnd, &margins);
}

unsafe fn apply(hwnd: HWND, palette: &Palette, backdrop: &str) {
    use windows::Win32::Foundation::COLORREF;
    use windows::Win32::Graphics::Dwm::{
        DwmSetWindowAttribute, DWMWA_BORDER_COLOR, DWMWA_CAPTION_COLOR, DWMWA_SYSTEMBACKDROP_TYPE,
        DWMWA_TEXT_COLOR, DWMWA_USE_IMMERSIVE_DARK_MODE, DWMWA_WINDOW_CORNER_PREFERENCE,
        DWMWCP_ROUND, DWMSBT_MAINWINDOW, DWMSBT_NONE, DWMSBT_TABBEDWINDOW,
        DWMSBT_TRANSIENTWINDOW, DWMWINDOWATTRIBUTE,
    };

    fn set<T>(hwnd: HWND, attr: DWMWINDOWATTRIBUTE, value: &T) {
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
    // the backdrop type is set. This flag works since Windows 10 1809.
    set(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, &(palette.dark as i32));
    set(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, &DWMWCP_ROUND);

    // The rest of the attributes only exist on Windows 11 22H2+; on older
    // builds the window keeps its system caption and that is fine.
    if windows_build() < 22621 {
        return;
    }

    let caption_none = COLORREF(0xff_ff_ff_fe);
    let caption = COLORREF(bgr(palette.bg));
    let text = COLORREF(bgr(palette.text));
    let border = COLORREF(bgr(palette.accent));

    match backdrop {
        // No material: the caption is painted in the palette background, like
        // the Python app's opaque look, and nothing sees through.
        "none" | "solid" => {
            unsafe { extend_frame(hwnd, 0) };
            set(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, &DWMSBT_NONE);
            set(hwnd, DWMWA_CAPTION_COLOR, &caption);
        }
        // Blur is an accent, not a system backdrop; the two would stack
        // (native.py set_backdrop's "blur" branch).
        "blur" => {
            unsafe { extend_frame(hwnd, -1) };
            set(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, &DWMSBT_NONE);
            unsafe { set_accent_blur_behind(hwnd) };
            set(hwnd, DWMWA_CAPTION_COLOR, &caption_none);
        }
        "mica" => {
            unsafe { extend_frame(hwnd, -1) };
            set(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, &DWMSBT_MAINWINDOW);
            set(hwnd, DWMWA_CAPTION_COLOR, &caption_none);
        }
        "mica_alt" => {
            unsafe { extend_frame(hwnd, -1) };
            set(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, &DWMSBT_TABBEDWINDOW);
            set(hwnd, DWMWA_CAPTION_COLOR, &caption_none);
        }
        "acrylic" => {
            unsafe { extend_frame(hwnd, -1) };
            set(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, &DWMSBT_TRANSIENTWINDOW);
            set(hwnd, DWMWA_CAPTION_COLOR, &caption_none);
        }
        _ => {
            // Unknown value: behave like solid so the window is not left
            // with a stale material.
            unsafe { extend_frame(hwnd, 0) };
            set(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, &DWMSBT_NONE);
            set(hwnd, DWMWA_CAPTION_COLOR, &caption);
        }
    }
    set(hwnd, DWMWA_TEXT_COLOR, &text);
    set(hwnd, DWMWA_BORDER_COLOR, &border);
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
