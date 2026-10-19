//! Start-with-Windows via the HKCU Run key, like src/freedictate/system.py.
//! Uses reg.exe because Cargo.toml has no Win32_System_Registry feature.

use std::path::Path;
use std::process::Command;

const RUN_KEY: &str = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run";
const RUN_VALUE: &str = "FreeDictate-Rust";

/// The string stored in the Run key: the exe path in quotes.
pub fn run_command(exe: &Path) -> String {
    format!("\"{}\"", exe.display())
}

fn reg(args: &[&str]) -> Result<String, String> {
    let mut cmd = Command::new("reg");
    cmd.args(args);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW, so no console flashes
    }
    let out = cmd
        .output()
        .map_err(|e| format!("could not run reg.exe: {e}"))?;
    let text = format!(
        "{}{}",
        String::from_utf8_lossy(&out.stdout),
        String::from_utf8_lossy(&out.stderr)
    );
    if out.status.success() {
        Ok(text)
    } else {
        Err(text)
    }
}

pub fn is_enabled() -> bool {
    reg(&["query", RUN_KEY, "/v", RUN_VALUE]).is_ok()
}

pub fn set_enabled(on: bool, exe: &Path) -> Result<(), String> {
    if on {
        return reg(&[
            "add",
            RUN_KEY,
            "/v",
            RUN_VALUE,
            "/t",
            "REG_SZ",
            "/d",
            &run_command(exe),
            "/f",
        ])
        .map(|_| ());
    }
    match reg(&["delete", RUN_KEY, "/v", RUN_VALUE, "/f"]) {
        Ok(_) => Ok(()),
        // Turning it off when it was never on is success, as in system.py.
        Err(e) if e.to_lowercase().contains("unable to find") => Ok(()),
        Err(e) => Err(e),
    }
}
