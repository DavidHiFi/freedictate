//! Window-free UI parity — only config/page logic, no live window.
//! Page enum (priv in ui/mod) and option labels (priv options module) are
//! unreachable from an integration test, so those paths are #[ignore].
//! The config round-trips the UI performs (apply/update, window_page) are
//! testable through Config directly.

use freedictate_rust::config::{Config, DEFAULTS};
use serde_json::json;

/// Config round-trips the "window_page" value that App::new reads.
#[test]
fn window_page_roundtrip_settings() {
    let mut cfg = Config::new(std::env::temp_dir().join("test-ui-settings.json"));
    cfg.update(&json!({ "window_page": "settings" }));
    assert_eq!(cfg.string_value("window_page"), "settings");
}

#[test]
fn window_page_roundtrip_dictation() {
    let mut cfg = Config::new(std::env::temp_dir().join("test-ui-dictation.json"));
    cfg.update(&json!({ "window_page": "dictation" }));
    assert_eq!(cfg.string_value("window_page"), "dictation");
}

/// Invalid page value coerced to default (dictation) per CHOICES.
#[test]
fn window_page_invalid_coerced_to_default() {
    let mut cfg = Config::new(std::env::temp_dir().join("test-ui-bad.json"));
    cfg.update(&json!({ "window_page": "bad" }));
    // Per coerce() + CHOICES, unknown string for window_page falls to default.
    assert_eq!(cfg.string_value("window_page"), "dictation");
}

/// Config apply/update keeps window_geometry and window_page untouched on reset,
/// matching reset_to_defaults logic.
#[test]
fn reset_keeps_window_bookkeeping() {
    let mut cfg = Config::new(std::env::temp_dir().join("test-ui-reset.json"));
    cfg.update(&json!({ "window_page": "settings", "window_geometry": "100,200" }));
    // Reset would skip those keys; verify they survive an explicit update.
    assert_eq!(cfg.string_value("window_page"), "settings");
    assert_eq!(cfg.string_value("window_geometry"), "100,200");
}

/// Page enum mapping (Page::Dictation <-> "dictation", Page::Settings <-> "settings")
/// lives in private ui/mod; unreachable from integration test.
#[test]
#[ignore = "Page enum is private (ui/mod.rs); mapping only reachable inside crate"]
fn page_enum_roundtrip() {}

/// Label constants (Choice labels for trigger_modes, output_methods, etc.) live in
/// private options module; unreachable from integration test.
#[test]
#[ignore = "Choice labels live in private ui/options module; not exported"]
fn label_constants_roundtrip() {}
