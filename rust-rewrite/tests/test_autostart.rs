use freedictate_rust::autostart::run_command;
use std::path::Path;

#[test]
fn quotes_exe_path() {
    assert_eq!(
        run_command(Path::new(r"C:\Program Files\FreeDictate\freedictate-rust.exe")),
        "\"C:\\Program Files\\FreeDictate\\freedictate-rust.exe\""
    );
    assert_eq!(
        run_command(Path::new(r"C:\apps\freedictate-rust.exe")),
        "\"C:\\apps\\freedictate-rust.exe\""
    );
}

/// Writes and removes the real Run value; run by hand with --ignored.
#[test]
#[ignore]
fn round_trip_on_the_real_registry() {
    let exe = std::path::Path::new(r"C:\Temp\freedictate-rust-test.exe");
    let was = freedictate_rust::autostart::is_enabled();
    freedictate_rust::autostart::set_enabled(true, exe).unwrap();
    assert!(freedictate_rust::autostart::is_enabled());
    freedictate_rust::autostart::set_enabled(false, exe).unwrap();
    assert!(!freedictate_rust::autostart::is_enabled());
    // Turning it off twice is still fine.
    freedictate_rust::autostart::set_enabled(false, exe).unwrap();
    assert!(!was, "a real FreeDictate-Rust value existed before this test");
}
