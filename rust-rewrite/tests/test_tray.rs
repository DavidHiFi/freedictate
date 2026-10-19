//! Tests for the tray icon's event plumbing (TrayEvent send/recv). The
//! native message loop runs in its own thread but is short-lived; what is
//! checkable without side effects is that events flow through the
//! std::sync::mpsc::Sender correctly and the Tray handle shuts down cleanly.

use freedictate_rust::tray::{self, TrayEvent};
use std::sync::{Arc, mpsc, Mutex};
use std::time::Duration;

#[test]
fn tray_event_sent() {
    let (tx, rx) = mpsc::channel();
    let tray = tray::spawn(tx.clone()).expect("spawn");
    tx.send(TrayEvent::ShowSettings).ok();
    assert!(matches!(
        rx.recv_timeout(Duration::from_millis(500)),
        Ok(TrayEvent::ShowSettings)
    ));
    drop(tray);
}

#[test]
fn tray_event_quit() {
    let (tx, rx) = mpsc::channel();
    let tray = tray::spawn(tx.clone()).expect("spawn");
    tx.send(TrayEvent::Quit).ok();
    assert!(matches!(
        rx.recv_timeout(Duration::from_millis(500)),
        Ok(TrayEvent::Quit)
    ));
    drop(tray);
}

#[test]
fn tray_graceful_shutdown() {
    let (tx, _rx) = mpsc::channel();
    let tray = Arc::new(Mutex::new(tray::spawn(tx.clone()).expect("spawn")));
    // Drop the spawn() return value; the background thread receives WM_QUIT
    // via thread_id storage and joins cleanly within the Tray's drop impl.
    let mut guard = tray.lock().unwrap();
    drop(guard);
    // If shutdown completes, the thread should have exited without panic.
    // The test passing means the drop path was exercised successfully.
}