use freedictate_rust::config::Config;
use serde_json::json;

#[test]
fn default_mute_level_is_silent() {
    let cfg = Config::new(std::env::temp_dir().join("freedictate-rust-defaults.json"));
    assert_eq!(cfg.number_value("isolate_output_level"), 0);
}

#[test]
fn stored_100_means_silent() {
    let path = std::env::temp_dir().join("freedictate-rust-100.json");
    let _ = std::fs::remove_file(&path);
    let mut cfg = Config::new(path.clone());
    cfg.update(&json!({ "isolate_output_while_dictating": true, "isolate_output_level": 100 }));
    assert_eq!(cfg.number_value("isolate_output_level"), 0);
    assert!(cfg.bool_value("isolate_output_while_dictating"));
    cfg.save().expect("settings must save");
    let loaded = Config::load_from(path.clone());
    assert_eq!(loaded.number_value("isolate_output_level"), 0);
    let _ = std::fs::remove_file(&path);
}

#[test]
fn load_snaps_offered_levels() {
    let path = std::env::temp_dir().join("freedictate-rust-load-steps.json");
    let _ = std::fs::remove_file(&path);
    std::fs::write(
        &path,
        r#"{ "isolate_output_level": 80, "mic_privacy_while_dictating": true }"#,
    )
    .expect("settings must write");
    let cfg = Config::load_from(path.clone());
    assert_eq!(cfg.number_value("isolate_output_level"), 50);
    assert!(cfg.bool_value("mic_privacy_while_dictating"));
    let _ = std::fs::remove_file(&path);
}

#[test]
fn offered_levels_stay_as_offered() {
    let path = std::env::temp_dir().join("freedictate-rust-steps.json");
    let _ = std::fs::remove_file(&path);
    let mut cfg = Config::new(path.clone());
    cfg.update(&json!({ "isolate_output_level": 25 }));
    cfg.update(&json!({ "isolate_output_level": 50 }));
    assert_eq!(cfg.number_value("isolate_output_level"), 50);
    cfg.update(&json!({ "isolate_output_level": 10 }));
    assert_eq!(cfg.number_value("isolate_output_level"), 0);
    let _ = std::fs::remove_file(&path);
}
