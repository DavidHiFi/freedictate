//! Startup-hang probe: `App::refresh_mics` calls `audio::input_devices()`
//! on the UI thread every tick, so a blocked WASAPI enumeration would freeze
//! the window before its first frame. The call runs on a detached thread and
//! the test joins it with a timeout, so a wedged audio stack fails the test
//! instead of hanging the suite.

use std::time::{Duration, Instant};

#[test]
fn input_devices_returns_within_30s() {
    let handle = std::thread::spawn(|| {
        let start = Instant::now();
        let devices = freedictate_rust::audio::input_devices();
        (start.elapsed(), devices.len())
    });
    let (elapsed, count) = handle
        .join()
        .unwrap_or_else(|_| (Duration::from_secs(31), 0));
    assert!(
        elapsed < Duration::from_secs(30),
        "input_devices blocked for {elapsed:?}"
    );
    println!("input_devices returned {count} devices in {elapsed:?}");
}
