//! Deliver finished text to the focused app: clipboard paste, typing, or
//! clipboard only. Windows clipboard and SendInput, as in the Python
//! `output.py` module.

use windows::core::PCWSTR;
use windows::Win32::Foundation::{HANDLE, HGLOBAL};
use windows::Win32::Security::{GetTokenInformation, TokenElevation, TOKEN_QUERY};
use windows::Win32::System::DataExchange::{
    CloseClipboard, EmptyClipboard, EnumClipboardFormats, GetClipboardData, GetClipboardSequenceNumber,
    OpenClipboard, RegisterClipboardFormatW, SetClipboardData,
};
use windows::Win32::System::Memory::{GlobalAlloc, GlobalLock, GlobalSize, GlobalUnlock, GMEM_MOVEABLE};
use windows::Win32::System::Threading::{
    OpenProcess, OpenProcessToken, QueryFullProcessImageNameW, PROCESS_NAME_WIN32,
    PROCESS_QUERY_LIMITED_INFORMATION,
};
use windows::Win32::UI::Input::KeyboardAndMouse::{
    GetAsyncKeyState, SendInput, KEYBDINPUT, KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP,
    KEYEVENTF_UNICODE, VIRTUAL_KEY, VK_CONTROL, VK_INSERT, VK_RETURN, VK_SHIFT, VK_V, INPUT,
    INPUT_KEYBOARD,
};
use windows::Win32::UI::WindowsAndMessaging::{GetForegroundWindow, GetWindowThreadProcessId};

pub const CF_UNICODETEXT: u32 = 13;

// Handle-based formats that are not global memory; Windows re-synthesizes them.
const GDI_FORMATS: [u32; 4] = [2, 3, 9, 14];

const TRANSIENT_FORMATS: [&str; 3] = [
    "ExcludeClipboardContentFromMonitorProcessing",
    "CanIncludeInClipboardHistory",
    "CanUploadToCloudClipboard",
];

fn registered(name: &str) -> u32 {
    let mut utf16: Vec<u16> = name.encode_utf16().collect();
    utf16.push(0);
    unsafe { RegisterClipboardFormatW(PCWSTR(utf16.as_ptr())) }
}

fn key_input(vk: VIRTUAL_KEY, scan: u16, flags: KEYBD_EVENT_FLAGS) -> KEYBDINPUT {
    KEYBDINPUT {
        wVk: vk,
        wScan: scan,
        dwFlags: flags,
        time: 0,
        dwExtraInfo: 0,
    }
}

use windows::Win32::UI::Input::KeyboardAndMouse::KEYBD_EVENT_FLAGS;

/// Send a batch of key events as one SendInput call.
fn send_batch(rows: &[KEYBDINPUT]) -> u32 {
    let inputs: Vec<INPUT> = rows
        .iter()
        .map(|ki| INPUT {
            r#type: INPUT_KEYBOARD,
            Anonymous: windows::Win32::UI::Input::KeyboardAndMouse::INPUT_0 { ki: *ki },
        })
        .collect();
    if inputs.is_empty() {
        return 0;
    }
    unsafe { SendInput(&inputs, std::mem::size_of::<INPUT>() as i32) }
}

fn chord(modifier: VIRTUAL_KEY, vk: VIRTUAL_KEY, extended: bool) {
    let ext = if extended { KEYEVENTF_EXTENDEDKEY } else { KEYBD_EVENT_FLAGS(0) };
    send_batch(&[
        key_input(modifier, 0, KEYBD_EVENT_FLAGS(0)),
        key_input(vk, 0, ext),
        key_input(vk, 0, ext | KEYEVENTF_KEYUP),
        key_input(modifier, 0, KEYEVENTF_KEYUP),
    ]);
}

pub fn press_enter() {
    send_batch(&[key_input(VK_RETURN, 0, KEYBD_EVENT_FLAGS(0)), key_input(VK_RETURN, 0, KEYEVENTF_KEYUP)]);
}

pub fn type_text(text: &str) {
    let mut batch: Vec<KEYBDINPUT> = Vec::new();
    for ch in text.replace("\r\n", "\n").chars() {
        if ch == '\n' {
            batch.push(key_input(VK_RETURN, 0, KEYBD_EVENT_FLAGS(0)));
            batch.push(key_input(VK_RETURN, 0, KEYEVENTF_KEYUP));
            continue;
        }
        let mut buffer = [0u16; 2];
        for code in ch.encode_utf16(&mut buffer) {
            batch.push(key_input(VIRTUAL_KEY(0), *code, KEYEVENTF_UNICODE));
            batch.push(key_input(VIRTUAL_KEY(0), *code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP));
        }
        if batch.len() >= 128 {
            send_batch(&batch);
            batch.clear();
        }
    }
    send_batch(&batch);
}

// ------------------------------------------------------------------ clipboard

fn open_clipboard(tries: usize) -> bool {
    for _ in 0..tries {
        if unsafe { OpenClipboard(None) }.is_ok() {
            return true;
        }
        std::thread::sleep(std::time::Duration::from_millis(15));
    }
    false
}

fn global_from_bytes(data: &[u8]) -> Option<HGLOBAL> {
    unsafe {
        let size = data.len().max(1);
        let h = match GlobalAlloc(GMEM_MOVEABLE, size) {
            Ok(h) => h,
            Err(_) => return None,
        };
        let p = GlobalLock(h);
        if !p.is_null() {
            std::ptr::copy_nonoverlapping(data.as_ptr(), p as *mut u8, data.len());
            let _ = GlobalUnlock(h);
        }
        Some(h)
    }
}

fn clipboard_bytes(handle: HANDLE) -> Option<Vec<u8>> {
    unsafe {
        let hg: HGLOBAL = std::mem::transmute(handle);
        let size = GlobalSize(hg);
        let p = GlobalLock(hg);
        if p.is_null() {
            return None;
        }
        let bytes = std::slice::from_raw_parts(p as *const u8, size).to_vec();
        let _ = GlobalUnlock(hg);
        Some(bytes)
    }
}

pub fn save_clipboard() -> Option<Vec<(u32, Vec<u8>)>> {
    if !open_clipboard(20) {
        return None;
    }
    let mut saved: Vec<(u32, Vec<u8>)> = Vec::new();
    unsafe {
        let mut fmt: u32 = 0;
        loop {
            fmt = EnumClipboardFormats(fmt);
            if fmt == 0 {
                break;
            }
            if GDI_FORMATS.contains(&fmt) {
                continue;
            }
            if let Ok(h) = GetClipboardData(fmt) {
                if let Some(bytes) = clipboard_bytes(h) {
                    saved.push((fmt, bytes));
                }
            }
        }
        let _ = CloseClipboard();
    }
    Some(saved)
}

pub fn restore_clipboard(saved: &[(u32, Vec<u8>)]) {
    if !open_clipboard(1) {
        return;
    }
    unsafe {
        let _ = EmptyClipboard();
        for (fmt, data) in saved {
            if let Some(h) = global_from_bytes(data) {
                let _ = SetClipboardData(*fmt, Some(std::mem::transmute::<HGLOBAL, HANDLE>(h)));
            }
        }
        let _ = CloseClipboard();
    }
}

pub fn set_clipboard(text: &str, transient: bool) -> bool {
    if !open_clipboard(20) {
        return false;
    }
    let mut ok = false;
    unsafe {
        let _ = EmptyClipboard();
        let mut bytes: Vec<u8> = text
            .encode_utf16()
            .flat_map(|c| c.to_le_bytes())
            .collect();
        bytes.extend_from_slice(&[0, 0]);
        if let Some(h) = global_from_bytes(&bytes) {
            let set = SetClipboardData(CF_UNICODETEXT, Some(std::mem::transmute::<HGLOBAL, HANDLE>(h)));
            ok = set.is_ok();
        }
        if ok && transient {
            let zero = [0u8; 4];
            for name in TRANSIENT_FORMATS {
                if let Some(h) = global_from_bytes(&zero) {
                    let _ = SetClipboardData(registered(name), Some(std::mem::transmute::<HGLOBAL, HANDLE>(h)));
                }
            }
        }
        let _ = CloseClipboard();
    }
    ok
}

pub fn get_clipboard_text() -> String {
    if !open_clipboard(1) {
        return String::new();
    }
    let mut out = String::new();
    unsafe {
        if let Ok(h) = GetClipboardData(CF_UNICODETEXT) {
            let hg: HGLOBAL = std::mem::transmute(h);
            let p = GlobalLock(hg);
            if !p.is_null() {
                let mut len = 0usize;
                while *p.cast::<u16>().add(len) != 0 {
                    len += 1;
                }
                let slice = std::slice::from_raw_parts(p as *const u16, len);
                out = String::from_utf16_lossy(slice);
                let _ = GlobalUnlock(hg);
            }
        }
        let _ = CloseClipboard();
    }
    out
}

// ------------------------------------------------------------------ target app

pub fn foreground_pid() -> u32 {
    unsafe {
        let hwnd = GetForegroundWindow();
        GetWindowThreadProcessId(hwnd, None)
    }
}

pub fn foreground_process_name() -> String {
    unsafe {
        let hwnd = GetForegroundWindow();
        let pid = GetWindowThreadProcessId(hwnd, None);
        if pid == 0 {
            return String::new();
        }
        let Ok(h) = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid) else {
            return String::new();
        };
        let mut buf = [0u16; 1024];
        let mut size = buf.len() as u32;
        let name = if QueryFullProcessImageNameW(h, PROCESS_NAME_WIN32, windows::core::PWSTR(buf.as_mut_ptr()), &mut size).is_ok()
        {
            String::from_utf16_lossy(&buf[..size as usize])
                .rsplit('\\')
                .next()
                .unwrap_or("")
                .to_string()
        } else {
            String::new()
        };
        let _ = windows::Win32::Foundation::CloseHandle(h);
        name
    }
}

fn is_elevated(pid: u32) -> Option<bool> {
    unsafe {
        let Ok(h) = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid) else {
            return None;
        };
        let mut token = HANDLE::default();
        if OpenProcessToken(h, TOKEN_QUERY, &mut token).is_err() {
            let _ = windows::Win32::Foundation::CloseHandle(h);
            return Some(true); // Denied to the token: it runs above us.
        }
        let mut value = 0u32;
        let mut returned = 0u32;
        let ok = GetTokenInformation(
            token,
            TokenElevation,
            Some(&mut value as *mut u32 as *mut core::ffi::c_void),
            4,
            &mut returned,
        )
        .is_ok();
        let _ = windows::Win32::Foundation::CloseHandle(token);
        let _ = windows::Win32::Foundation::CloseHandle(h);
        if ok {
            Some(value != 0)
        } else {
            None
        }
    }
}

pub fn self_elevated() -> bool {
    is_elevated(std::process::id()).unwrap_or(false)
}

pub fn target_blocks_input() -> bool {
    let pid = foreground_pid();
    is_elevated(pid).unwrap_or(false) && !self_elevated()
}

// -------------------------------------------------------------------- deliver

fn modifier_down(vk: u16) -> bool {
    unsafe { GetAsyncKeyState(vk as i32) as u16 & 0x8000 != 0 }
}

pub fn wait_for_modifiers_release() {
    const MODIFIER_VKS: [u16; 8] = [0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C];
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(2);
    while std::time::Instant::now() < deadline && MODIFIER_VKS.iter().any(|vk| modifier_down(*vk)) {
        std::thread::sleep(std::time::Duration::from_millis(10));
    }
}

/// Deliver text. Returns what happened, for logging: "pasted", "typed",
/// "copied", or "blocked" (admin window; text left on the clipboard).
pub fn deliver(text: &str, method: &str, restore: bool, delay_ms: u32) -> &'static str {
    if method == "clipboard" {
        set_clipboard(text, false);
        return "copied";
    }
    wait_for_modifiers_release();
    if target_blocks_input() {
        set_clipboard(text, false);
        return "blocked";
    }
    if delay_ms > 0 {
        std::thread::sleep(std::time::Duration::from_millis(delay_ms as u64));
    }
    if method == "type" {
        type_text(text);
        return "typed";
    }
    let saved = if restore { save_clipboard() } else { None };
    if !set_clipboard(text, restore && saved.is_some()) {
        if let Some(items) = &saved {
            restore_clipboard(items);
        }
        type_text(text);
        return "typed";
    }
    let seq_before = unsafe { GetClipboardSequenceNumber() };
    if method == "paste_shift_insert" {
        chord(VK_SHIFT, VK_INSERT, true);
    } else {
        chord(VK_CONTROL, VK_V, false);
    }
    if let Some(items) = &saved {
        // The target reads the clipboard after it handles the keystroke.
        std::thread::sleep(std::time::Duration::from_millis(450));
        let seq_now = unsafe { GetClipboardSequenceNumber() };
        if seq_now == seq_before {
            restore_clipboard(items);
        }
    }
    "pasted"
}
