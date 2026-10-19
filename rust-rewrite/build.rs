//! Build script: gives the exe the FreeDictate icon so the taskbar and
//! Explorer show the microphone mark instead of the Rust default. The same
//! .ico feeds the tray icon at runtime (src/tray.rs).

fn main() {
    if std::env::var("CARGO_CFG_WINDOWS").is_ok() {
        winresource::WindowsResource::new()
            .set_icon("../assets/freedictate.ico")
            .compile()
            .expect("embed the FreeDictate icon");
    }
}
