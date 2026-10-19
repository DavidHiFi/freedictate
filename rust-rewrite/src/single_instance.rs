//! Single-instance guard (port of src/freedictate/app.py's QLocalServer +
//! QLocalSocket + _signal_running). Mirrors the same name pattern
//! `FreeDictate-<username>` but keeps the Rust app's own namespace
//! `FreeDictate-Rust-<username>`, so it never talks to the Python app.
//!
//! Deviation from Python: instead of a local socket server, ownership is a
//! named mutex and the wake signal is a registered window message. The
//! mutex name pattern is the same idea as Python's SERVER_NAME.

use std::collections::HashMap;
use std::sync::{atomic::{AtomicBool, Ordering}, Mutex};

use windows::core::PCWSTR;
use windows::Win32::Foundation::{ERROR_ALREADY_EXISTS, LPARAM, WPARAM};
use windows::Win32::System::Threading::CreateMutexW;

// Handles for mutexes this process owns. CreateMutexW's handle must stay
// open for as long as the instance should count as running; dropping the
// HANDLE value would let the next guard() take the name over.
static HELD: Mutex<Option<HashMap<String, isize>>> = Mutex::new(None);
static OWNED: AtomicBool = AtomicBool::new(false);
static WAKE_MSGS: Mutex<Option<HashMap<String, u32>>> = Mutex::new(None);

pub fn wake_message() -> u32 {
    wake_message_for(&username())
}

/// Registered window message for one user's wake broadcast. Per user, so a
/// second instance never wakes another account's window.
fn wake_message_for(user: &str) -> u32 {
    let mut map = WAKE_MSGS.lock().unwrap();
    let map = map.get_or_insert_with(HashMap::new);
    *map.entry(user.to_string()).or_insert_with(|| {
        let name = format!("FreeDictateRustWake-{user}");
        let s = name.encode_utf16().chain(Some(0)).collect::<Vec<u16>>();
        unsafe { windows::Win32::UI::WindowsAndMessaging::RegisterWindowMessageW(PCWSTR(s.as_ptr())) }
    })
}

fn username() -> String {
    std::env::var("USERNAME").unwrap_or_else(|_| {
        std::env::var("USER").unwrap_or_else(|_| "user".to_string())
    })
}

fn to_wide(s: &str) -> Vec<u16> { s.encode_utf16().chain(Some(0)).collect() }

pub fn guard() -> Result<(), String> {
    let name = format!("FreeDictate-Rust-{}", username());
    let wide = to_wide(&name);
    // The handle stays open for the process lifetime (kept as a raw value in
    // HELD, since HANDLE is not Send); nothing ever closes it on purpose.
    let mutex = unsafe { CreateMutexW(None, true, PCWSTR(wide.as_ptr())) }.map_err(|e| e.to_string())?;
    let already = unsafe { windows::Win32::Foundation::GetLastError() } == ERROR_ALREADY_EXISTS;
    if already {
        if HELD.lock().unwrap().as_ref().is_some_and(|m| m.contains_key(&name)) {
            // This process already owns the mutex: guard() is idempotent.
            return Ok(());
        }
        // Another instance owns it: wake that one's window, then refuse.
        let class = format!("FreeDictateRustInstance-{}", username());
        let wide = to_wide(&class);
        let msg = wake_message();
        if let Ok(hwnd) = unsafe { windows::Win32::UI::WindowsAndMessaging::FindWindowW(PCWSTR(wide.as_ptr()), None) } {
            let _ = unsafe { windows::Win32::UI::WindowsAndMessaging::PostMessageW(Some(hwnd), msg, WPARAM(0), LPARAM(0)) };
        }
        return Err("already running".into());
    }
    HELD.lock().unwrap().get_or_insert_with(HashMap::new).insert(name, mutex.0 as isize);
    OWNED.store(true, Ordering::SeqCst);
    Ok(())
}

pub fn is_owner() -> bool { OWNED.load(Ordering::SeqCst) }