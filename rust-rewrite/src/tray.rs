//! Windows system tray icon (port of src/freedictate/app.py's QSystemTrayIcon).
//!
//! Spawns a background thread that owns a hidden message-only window, runs a
//! message pump, and uses Shell_NotifyIconW to show the tray icon. Left-click
//! and the "Settings" menu item emit TrayEvent::ShowSettings; "Exit" emits
//! TrayEvent::Quit. The event plumbing is pure so it can be unit-tested.

use std::path::PathBuf;
use std::sync::mpsc::Sender;
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::thread::JoinHandle;

use windows::core::{PCWSTR, BOOL};
use windows::Win32::Foundation::{HWND, HANDLE, WPARAM, LPARAM, POINT};
use windows::Win32::UI::Shell::{NOTIFYICONDATAW, NOTIFY_ICON_DATA_FLAGS, NIM_ADD, NIM_DELETE};
use windows::Win32::UI::WindowsAndMessaging::HICON;
use windows::Win32::UI::WindowsAndMessaging::{
    CreateWindowExW, DefWindowProcW, DispatchMessageW, GetCursorPos,
    GetMessageW, LoadImageW, PostThreadMessageW, WINDOW_EX_STYLE, WS_OVERLAPPED, HWND_MESSAGE, HMENU,
    WM_DESTROY, WM_USER, WM_LBUTTONUP, WM_RBUTTONUP, WM_NULL, WM_QUIT,
    MSG, LR_LOADFROMFILE, LR_DEFAULTSIZE, IMAGE_ICON, MF_STRING,
};

// Raw FFI for functions not available via enabled features
#[link(name = "user32")]
#[allow(improper_ctypes)]
extern "system" {
    fn SetForegroundWindow(hwnd: HWND) -> BOOL;
    fn PostMessageW(hwnd: HWND, msg: u32, wparam: WPARAM, lparam: LPARAM) -> BOOL;
    fn RegisterClassW(lpwndclass: *const WNDCLASSW) -> u16;
    fn AppendMenuW(hmenu: HMENU, uflags: u32, uidnewitem: usize, lpnewitem: PCWSTR) -> BOOL;
    fn CreatePopupMenu() -> HMENU;
    fn DestroyMenu(hmenu: HMENU) -> BOOL;
    fn TrackPopupMenu(hmenu: HMENU, uflags: u32, x: i32, y: i32,
        nreserved: Option<i32>, hwnd: HWND, prcrect: Option<*const RECT>) -> BOOL;
}

#[link(name = "kernel32")]
extern "system" {
    fn GetCurrentThreadId() -> u32;
}

#[repr(C)]
#[derive(Clone, Copy)]
// Field names follow the Win32 API the struct mirrors.
#[allow(non_snake_case)]
struct WNDCLASSW {
    style: u32,
    lpfnWndProc: Option<unsafe extern "system" fn(HWND, u32, usize, isize) -> isize>,
    hInstance: HANDLE,
    hCursor: HANDLE,
    hbrBackground: HANDLE,
    lpszMenuName: PCWSTR,
    lpszClassName: PCWSTR,
}

#[repr(C)]
struct RECT { left: i32, top: i32, right: i32, bottom: i32 }

pub enum TrayEvent { ShowSettings, Quit }

const WCLASS: &str = "FreeDictateRustInstance";
const ICON_FILE: &str = "freedictate.ico";
const IDM_SETTINGS: usize = 1;
const IDM_EXIT: usize = 2;
const WM_TRAY: u32 = WM_USER + 1;

const NIF_ICON: u32 = 0x00000002;
const NIF_MESSAGE: u32 = 0x00000001;
const NIF_TIP: u32 = 0x00000004;
const TPM_RIGHTBUTTON: u32 = 0x0002;
const TPM_RETURNCMD: u32 = 0x0100;
const TPM_NONOTIFY: u32 = 0x0008;

fn to_wide(s: &str) -> Vec<u16> { s.encode_utf16().chain(Some(0)).collect() }

fn ic_path() -> PathBuf {
    let appdata = std::env::var("APPDATA").unwrap_or_else(|_| r"C:\Users\default\AppData\Roaming".into());
    let dir = PathBuf::from(appdata).join("FreeDictate-Rust");
    let p = dir.join(ICON_FILE);
    let _ = std::fs::create_dir_all(&dir);
    p
}

fn copy_icon() -> Result<(), String> {
    let p = ic_path();
    if p.exists() { return Ok(()); }
    let embedded: &[u8] = include_bytes!(concat!(env!("CARGO_MANIFEST_DIR"), "/../assets/freedictate.ico"));
    std::fs::write(&p, embedded).map_err(|e| format!("icon copy: {e}"))
}

fn load_icon(path: &str) -> Option<HICON> {
    let w = to_wide(path);
    unsafe {
        let h = LoadImageW(None, PCWSTR(w.as_ptr()), IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE);
        match h { Ok(handle) => Some(HICON(handle.0)), Err(_) => None }
    }
}

static TRAY_SENDER: std::sync::OnceLock<std::sync::Mutex<Option<Sender<TrayEvent>>>> = std::sync::OnceLock::new();

unsafe extern "system" fn wnd_proc(hwnd: HWND, msg: u32, wparam: usize, lparam: isize) -> isize {
    // A second instance posts this registered message to wake us.
    if msg == crate::single_instance::wake_message() {
        if let Some(sender) = TRAY_SENDER.get().and_then(|m| m.lock().ok()).and_then(|g| g.clone()) {
            let _ = sender.send(TrayEvent::ShowSettings);
        }
        return 0;
    }
    match msg {
        WM_DESTROY => {
            let _ = PostThreadMessageW(GetCurrentThreadId(), WM_QUIT, WPARAM(0), LPARAM(0));
            0
        }
        WM_TRAY => {
            let event = lparam as u32;
            if event == WM_LBUTTONUP {
                if let Some(sender) = TRAY_SENDER.get().and_then(|m| m.lock().ok()).and_then(|g| g.clone()) {
                    let _ = sender.send(TrayEvent::ShowSettings);
                }
            } else if event == WM_RBUTTONUP {
                let mut pt = POINT { x: 0, y: 0 };
                let _ = GetCursorPos(&mut pt);
                let _ = SetForegroundWindow(hwnd);
                let _ = PostMessageW(hwnd, WM_NULL, WPARAM(0), LPARAM(0));
                let hmenu = CreatePopupMenu();
                if hmenu.0.is_null() { return 0; }
                let settings_w = to_wide("Settings");
                let exit_w = to_wide("Exit");
                let _ = AppendMenuW(hmenu, MF_STRING.0, IDM_SETTINGS, PCWSTR(settings_w.as_ptr()));
                let _ = AppendMenuW(hmenu, MF_STRING.0, IDM_EXIT, PCWSTR(exit_w.as_ptr()));
                let cmd = TrackPopupMenu(hmenu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
                    pt.x, pt.y, Some(0), hwnd, None);
                let _ = DestroyMenu(hmenu);
                if cmd.0 == IDM_SETTINGS as i32 {
                    if let Some(sender) = TRAY_SENDER.get().and_then(|m| m.lock().ok()).and_then(|g| g.clone()) {
                        let _ = sender.send(TrayEvent::ShowSettings);
                    }
                } else if cmd.0 == IDM_EXIT as i32 {
                    if let Some(sender) = TRAY_SENDER.get().and_then(|m| m.lock().ok()).and_then(|g| g.clone()) {
                        let _ = sender.send(TrayEvent::Quit);
                    }
                }
            }
            0
        }
        _ => DefWindowProcW(hwnd, msg, WPARAM(wparam), LPARAM(lparam)).0 as isize,
    }
}

pub struct Tray {
    thread: Option<JoinHandle<()>>,
    thread_id: AtomicU32,
    stopped: AtomicBool,
}

impl Tray {
    pub fn shutdown(&mut self) {
        if self.stopped.swap(true, Ordering::SeqCst) { return; }
        let tid = self.thread_id.load(Ordering::SeqCst);
        if tid != 0 { let _ = unsafe { PostThreadMessageW(tid, WM_QUIT, WPARAM(0), LPARAM(0)) }; }
        if let Some(h) = self.thread.take() { let _ = h.join(); }
    }
}

impl Drop for Tray { fn drop(&mut self) { self.shutdown(); } }

pub fn spawn(sender: Sender<TrayEvent>) -> Result<Tray, String> {
    copy_icon()?;
    let (tx, rx) = std::sync::mpsc::channel::<u32>();
    let thread = std::thread::spawn(move || {
        // The per-user instance class is the one the single-instance guard
        // searches for, so a second launch wakes this window.
        let cls = to_wide(&format!("{WCLASS}-{}", crate::single_instance::username()));
        let wc = WNDCLASSW {
            style: 0,
            lpfnWndProc: Some(wnd_proc),
            hInstance: HANDLE(std::ptr::null_mut()),
            hCursor: HANDLE(std::ptr::null_mut()),
            hbrBackground: HANDLE(std::ptr::null_mut()),
            lpszMenuName: PCWSTR::null(),
            lpszClassName: PCWSTR(cls.as_ptr()),
        };
        unsafe { RegisterClassW(&wc); }
        let hwnd = unsafe { CreateWindowExW(WINDOW_EX_STYLE(0), PCWSTR(cls.as_ptr()), PCWSTR::null(), WS_OVERLAPPED, 0, 0, 0, 0, Some(HWND_MESSAGE), None, None, None) };
        let hwnd = match hwnd { Ok(h) if !h.0.is_null() => h, _ => return };
        let hicon = load_icon(ic_path().to_str().unwrap_or(""));
        let mut nid: NOTIFYICONDATAW = unsafe { std::mem::zeroed() };
        nid.cbSize = std::mem::size_of::<NOTIFYICONDATAW>() as u32;
        nid.hWnd = hwnd;
        nid.uID = 1;
        nid.uFlags = NOTIFY_ICON_DATA_FLAGS(NIF_ICON | NIF_MESSAGE | NIF_TIP);
        nid.uCallbackMessage = WM_TRAY;
        nid.hIcon = hicon.unwrap_or(HICON(std::ptr::null_mut()));
        let tip = to_wide("FreeDictate");
        for (i, &ch) in tip.iter().enumerate().take(127) { nid.szTip[i] = ch; }
        let _ = unsafe { windows::Win32::UI::Shell::Shell_NotifyIconW(NIM_ADD, &nid) };
        let tid = unsafe { GetCurrentThreadId() };
        let _ = tx.send(tid);
        TRAY_SENDER.get_or_init(|| std::sync::Mutex::new(None)).lock().unwrap().replace(sender);
        let mut msg = MSG::default();
        loop {
            let r = unsafe { GetMessageW(&mut msg, None, 0, 0) };
            if !r.as_bool() { break; }
            unsafe { DispatchMessageW(&msg); }
        }
        let _ = unsafe { windows::Win32::UI::Shell::Shell_NotifyIconW(NIM_DELETE, &nid) };
    });
    let thread_id = rx.recv().unwrap_or(0);
    Ok(Tray { thread: Some(thread), thread_id: AtomicU32::new(thread_id), stopped: AtomicBool::new(false) })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::mpsc;
    use std::time::Duration;

    #[test]
    fn tray_event_sent() {
        let (tx, rx) = mpsc::channel();
        let _tray = spawn(tx.clone()).expect("spawn");
        tx.send(TrayEvent::ShowSettings).ok();
        assert!(matches!(rx.recv_timeout(Duration::from_millis(500)), Ok(TrayEvent::ShowSettings)));
    }

    #[test]
    fn tray_event_quit() {
        let (tx, rx) = mpsc::channel();
        let _tray = spawn(tx.clone()).expect("spawn");
        tx.send(TrayEvent::Quit).ok();
        assert!(matches!(rx.recv_timeout(Duration::from_millis(500)), Ok(TrayEvent::Quit)));
    }
}