// Config parity tests, ported from tests/test_config.py.
// Only the offline-testable behaviour is ported: the Python file uses a
// pytest tmp_path, a change-listener callback and an export/import pair.
// The Rust Config has no listeners and no export/import, so those parts are
// reported as gaps instead of being faked here.

use std::fs;
use std::path::{Path, PathBuf};

use freedictate_rust::config::{Config, DEFAULTS};
use serde_json::{json, Value};

fn defaults() -> Value {
    serde_json::from_str(DEFAULTS).expect("DEFAULTS is valid json")
}

/// A scratch folder under the temp dir, so a test never writes into the repo.
fn scratch(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join("freedictate-rust-tests").join(name);
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).expect("scratch folder");
    dir
}

fn write_settings(dir: &Path, name: &str, text: &str) -> PathBuf {
    let path = dir.join(name);
    fs::write(&path, text).expect("write settings");
    path
}

#[test]
fn defaults_match_the_python_defaults() {
    let d = defaults();
    // The keys the Python DEFAULTS carries and the UI leans on.
    assert_eq!(d["hotkey"], json!("ctrl+win"));
    assert_eq!(d["hotkey_mode"], json!("hold"));
    assert_eq!(d["cancel_key"], json!("esc"));
    assert_eq!(d["model"], json!("small.en"));
    assert_eq!(d["output"], json!("paste"));
    assert_eq!(d["theme"], json!("Catppuccin Mocha"));
    assert_eq!(d["backdrop"], json!("mica_alt"));
    assert_eq!(d["tint"], json!(65));
    assert_eq!(d["cpu_threads"], json!(6));
    assert_eq!(d["beam_size"], json!(5));
    assert_eq!(d["idle_unload"], json!(true));
    assert_eq!(d["idle_seconds"], json!(0));
}

#[test]
fn defaults_and_coercion() {
    let dir = scratch("config-coercion");
    let path = write_settings(
        &dir,
        "settings.json",
        r#"{"tint": 500, "backdrop": "rainbow", "sounds": 0, "beam_size": "3",
             "unknown": 1, "replacements": [{"find": " x ", "replace": "y"}, {"find": ""}]}"#,
    );
    let c = Config::load_from(path);

    // tint is clamped into its 0-100 range.
    assert_eq!(c.number_value("tint"), 100);
    // backdrop is a choice: an unknown value falls back to the default.
    assert_eq!(c.string_value("backdrop"), defaults()["backdrop"]);
    // sounds is a bool: a number is read as a bool.
    assert!(!c.bool_value("sounds"));
    // replacements keeps only the entries with a non-empty find.
    let reps = c.get("replacements").and_then(Value::as_array).expect("array");
    assert_eq!(reps.len(), 1);
    assert_eq!(reps[0]["find"], json!(" x "));
    assert_eq!(reps[0]["replace"], json!("y"));
    // An unknown key is never stored.
    assert!(c.get("unknown").is_none());
}

#[test]
fn a_saved_file_is_loaded_and_coerced() {
    let dir = scratch("config-load");
    let path = write_settings(&dir, "settings.json", r#"{"theme": "Nord", "tint": 65}"#);
    let c = Config::load_from(path);
    assert_eq!(c.string_value("theme"), "Nord");
    assert_eq!(c.number_value("tint"), 65);
}

#[test]
fn update_only_touches_known_keys() {
    let dir = scratch("config-update");
    let mut c = Config::new(dir.join("settings.json"));
    c.update(&json!({"theme": "Nord", "unknown": 1, "tint": 500}));
    assert_eq!(c.string_value("theme"), "Nord");
    assert!(c.get("unknown").is_none());
    assert_eq!(c.number_value("tint"), 100);
}

#[test]
fn update_save_and_load_round_trip() {
    let dir = scratch("config-roundtrip");
    let path = dir.join("settings.json");
    let mut c = Config::new(path.clone());
    c.update(&json!({"theme": "Dracula", "hotkey": "rctrl", "cpu_threads": 9, "tint": 40}));
    c.save().expect("save");

    let loaded = Config::load_from(path);
    assert_eq!(loaded.string_value("theme"), "Dracula");
    assert_eq!(loaded.string_value("hotkey"), "rctrl");
    assert_eq!(loaded.number_value("cpu_threads"), 9);
    assert_eq!(loaded.number_value("tint"), 40);
}

#[test]
fn save_writes_readable_json() {
    let dir = scratch("config-save");
    let path = dir.join("settings.json");
    let mut c = Config::new(path.clone());
    c.update(&json!({"theme": "Nord"}));
    c.save().expect("save");

    let text = fs::read_to_string(&path).expect("read back");
    let parsed: Value = serde_json::from_str(&text).expect("saved file is json");
    assert_eq!(parsed["theme"], json!("Nord"));
}

#[test]
fn a_broken_settings_file_falls_back_to_the_defaults() {
    let dir = scratch("config-broken");
    let path = write_settings(&dir, "settings.json", "{not json");
    let c = Config::load_from(path);
    assert_eq!(c.string_value("theme"), defaults()["theme"].as_str().unwrap());
}

#[test]
fn a_non_object_settings_file_falls_back_to_the_defaults() {
    let dir = scratch("config-non-object");
    let path = write_settings(&dir, "settings.json", "[1, 2, 3]");
    let c = Config::load_from(path);
    assert_eq!(c.string_value("theme"), defaults()["theme"].as_str().unwrap());
}

#[test]
fn numeric_settings_are_clamped_to_their_range() {
    let mut c = Config::new(PathBuf::from("unused.json"));
    c.update(&json!({
        "tint": 500,
        "sound_volume": -20,
        "max_seconds": 99999,
        "auto_stop_silence": 90,
        "cpu_threads": 500,
        "beam_size": 0,
        "min_seconds": 0.0,
        "silence_peak": 9.0,
        "paste_delay_ms": 99999,
        "idle_seconds": 99999,
    }));
    assert_eq!(c.number_value("tint"), 100);
    assert_eq!(c.number_value("sound_volume"), 0);
    assert_eq!(c.number_value("max_seconds"), 3600);
    assert_eq!(c.number_value("auto_stop_silence"), 30);
    assert_eq!(c.number_value("cpu_threads"), 64);
    assert_eq!(c.number_value("beam_size"), 1);
    assert_eq!(c.float_value("min_seconds"), 0.1);
    assert_eq!(c.float_value("silence_peak"), 0.2);
    assert_eq!(c.number_value("paste_delay_ms"), 1000);
    assert_eq!(c.number_value("idle_seconds"), 3600);
}

#[test]
fn a_negative_idle_timeout_becomes_zero() {
    let mut c = Config::new(PathBuf::from("unused.json"));
    c.update(&json!({"idle_seconds": -3}));
    assert_eq!(c.number_value("idle_seconds"), 0);
}

#[test]
fn an_idle_timeout_is_capped_at_one_hour() {
    let mut c = Config::new(PathBuf::from("unused.json"));
    c.update(&json!({"idle_seconds": 5000}));
    assert_eq!(c.number_value("idle_seconds"), 3600);
}

#[test]
fn the_isolate_level_snaps_to_a_menu_choice() {
    let mut c = Config::new(PathBuf::from("unused.json"));
    c.update(&json!({"isolate_output_level": 100}));
    assert_eq!(c.number_value("isolate_output_level"), 0);
    c.update(&json!({"isolate_output_level": 30}));
    assert_eq!(c.number_value("isolate_output_level"), 25);
    c.update(&json!({"isolate_output_level": 40}));
    assert_eq!(c.number_value("isolate_output_level"), 50);
}

#[test]
fn a_bool_setting_reads_text_as_a_bool() {
    let mut c = Config::new(PathBuf::from("unused.json"));
    c.update(&json!({"sounds": "false"}));
    assert!(!c.bool_value("sounds"));
    c.update(&json!({"sounds": "on"}));
    assert!(c.bool_value("sounds"));
}

#[test]
fn an_unknown_choice_falls_back_to_the_default() {
    let mut c = Config::new(PathBuf::from("unused.json"));
    c.update(&json!({"hotkey_mode": "sideways"}));
    assert_eq!(c.string_value("hotkey_mode"), "hold");
    c.update(&json!({"hotkey_mode": "toggle"}));
    assert_eq!(c.string_value("hotkey_mode"), "toggle");
}

#[test]
fn the_configured_value_types_are_the_documented_ones() {
    let d = defaults();
    assert!(d["history_enabled"].is_boolean());
    assert!(d["ai_tidy"].is_boolean());
    assert!(d["ai_model"].is_string());
    assert!(d["idle_unload"].is_boolean());
    assert!(d["auto_submit"].is_boolean());
    assert!(d["trailing_space"].is_boolean());

    // The same types must survive a save and load.
    let dir = scratch("config-types");
    let path = dir.join("settings.json");
    let mut c = Config::new(path.clone());
    c.save().expect("save");
    let loaded = Config::load_from(path);
    assert!(loaded.get("history_enabled").unwrap().is_boolean());
    assert!(loaded.get("ai_tidy").unwrap().is_boolean());
    assert!(loaded.get("ai_model").unwrap().is_string());
    assert!(loaded.get("idle_unload").unwrap().is_boolean());
    assert!(loaded.get("auto_submit").unwrap().is_boolean());
    assert!(loaded.get("trailing_space").unwrap().is_boolean());
}
