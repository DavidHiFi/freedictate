// No console window in release builds; debug builds keep it for logs.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() -> iced::Result {
    // `--settings <path>` points at another settings file, for testing.
    let mut args = std::env::args().skip(1);
    let mut cfg_path = None;
    while let Some(arg) = args.next() {
        if arg == "--settings" {
            cfg_path = args.next().map(std::path::PathBuf::from);
        }
    }
    // One instance per user: a second launch wakes the running window and
    // exits (app.py _signal_running). A --settings run skips the guard so
    // tests can run alongside the real app.
    if cfg_path.is_none() && freedictate_rust::single_instance::guard().is_err() {
        return Ok(());
    }
    freedictate_rust::ui::run(cfg_path)
}
