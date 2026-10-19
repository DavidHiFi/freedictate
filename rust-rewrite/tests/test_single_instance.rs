//! Tests for the single-instance guard. Uses unique names per test to avoid
//! interference with other instances of the app (including the Python one).
//!
//! The guard uses the environment variable USERNAME to build its names. To
//! get a deterministic yet unique namespace for each test we temporarily
//! overwrite USERNAME — and hold one lock so the parallel test threads
//! cannot race each other's environment.

use std::env;
use std::sync::{Mutex, MutexGuard, OnceLock};

use freedictate_rust::single_instance;

fn serial_lock() -> MutexGuard<'static, ()> {
    static SERIAL: OnceLock<Mutex<()>> = OnceLock::new();
    SERIAL.get_or_init(|| Mutex::new(())).lock().unwrap()
}

fn with_username<F, R>(name: &str, f: F) -> R
where
    F: FnOnce() -> R,
{
    let prev = env::var("USERNAME").ok();
    env::set_var("USERNAME", name);
    let out = f();
    if let Some(v) = prev {
        env::set_var("USERNAME", v);
    } else {
        env::remove_var("USERNAME");
    }
    out
}

#[test]
fn guard_first_instance() {
    let _serial = serial_lock();
    with_username("testuser-guarded", || {
        assert!(single_instance::guard().is_ok());
        assert!(single_instance::is_owner());
    });
}

#[test]
fn guard_is_idempotent_in_process() {
    // A second guard() in the SAME process is the same instance: it stays
    // Ok. What gets refused is a second OS process, and that path needs a
    // real second process to test, so it is not scriptable here.
    let _serial = serial_lock();
    with_username("testuser-second", || {
        assert!(single_instance::guard().is_ok());
        assert!(single_instance::is_owner());
        assert!(single_instance::guard().is_ok());
        assert!(single_instance::is_owner());
    });
}

#[test]
fn guard_is_reentrant() {
    let _serial = serial_lock();
    with_username("testuser-reentrant", || {
        assert!(single_instance::guard().is_ok());
        assert!(single_instance::guard().is_ok());
    });
}

#[test]
fn wake_message_is_unique() {
    let _serial = serial_lock();
    with_username("user1", || {
        let msg1 = single_instance::wake_message();
        with_username("user2", || {
            let msg2 = single_instance::wake_message();
            assert_ne!(msg1, msg2);
        });
    });
}