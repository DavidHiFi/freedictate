use std::path::PathBuf;

use serde_json::Value;

pub const DEFAULTS: &str = r#"{
  "hotkey": "ctrl+win",
  "hotkey_mode": "hold",
  "cancel_key": "esc",
  "model": "small.en",
  "language": "en",
  "input_device": "",
  "sounds": true,
  "sound_volume": 50,
  "max_seconds": 600,
  "auto_stop_silence": 0,
  "vocabulary": "",
  "output": "paste",
  "restore_clipboard": true,
  "trailing_space": true,
  "remove_fillers": true,
  "remove_repeats": true,
  "capitalize": true,
  "end_punctuation": true,
  "voice_commands": true,
  "replacements": [],
  "auto_submit": false,
  "ai_tidy": false,
  "ai_model": "standard",
  "mic_privacy_while_dictating": false,
  "isolate_output_while_dictating": false,
  "isolate_output_level": 0,
  "overlay": true,
  "overlay_position": "bottom",
  "overlay_timer": true,
  "overlay_backdrop": "solid",
  "theme": "Catppuccin Mocha",
  "accent_source": "theme",
  "font": "Segoe UI Variable Text",
  "backdrop": "mica_alt",
  "tint": 65,
  "backdrop_when_inactive": false,
  "titlebar": "custom",
  "reduce_motion": false,
  "run_elevated": false,
  "history_enabled": true,
  "history_days": 0,
  "check_updates": true,
  "update_prereleases": false,
  "skipped_version": "",
  "last_update_check": 0,
  "device": "auto",
  "compute_type": "auto",
  "cpu_threads": 6,
  "beam_size": 5,
  "vad": true,
  "min_seconds": 0.4,
  "silence_peak": 0.004,
  "paste_delay_ms": 40,
  "idle_unload": true,
  "idle_seconds": 0,
  "first_run_done": false,
  "window_geometry": "",
  "settings_section": "general",
  "window_page": "dictation"
}"#;

pub const CHOICES: &[(&str, &[&str])] = &[
    ("hotkey_mode", &["hold", "toggle", "both"]),
    ("output", &["paste", "paste_shift_insert", "type", "clipboard"]),
    ("overlay_position", &["bottom", "top"]),
    ("accent_source", &["theme", "windows"]),
    ("backdrop", &["mica_alt", "mica", "acrylic", "blur", "solid"]),
    ("ai_model", &["light", "standard"]),
    ("overlay_backdrop", &["mica_alt", "mica", "acrylic", "blur", "solid"]),
    ("titlebar", &["custom", "windows"]),
    ("device", &["auto", "cpu", "cuda"]),
    ("compute_type", &["auto", "int8", "int8_float16", "float16", "float32"]),
    ("window_page", &["dictation", "settings"]),
];

pub const QUIET_STEPS: [u32; 3] = [0, 25, 50];

fn quiet_step(value: u32) -> u32 {
    if value >= 100 {
        0
    } else {
        *QUIET_STEPS
            .iter()
            .min_by_key(|step| (**step as i32 - value as i32).abs())
            .unwrap_or(&0)
    }
}

fn range_for(key: &str) -> Option<(f64, f64)> {
    match key {
        "sound_volume" | "isolate_output_level" => Some((0.0, 100.0)),
        "max_seconds" => Some((10.0, 3600.0)),
        "auto_stop_silence" => Some((0.0, 30.0)),
        "tint" => Some((0.0, 100.0)),
        "history_days" => Some((0.0, 3650.0)),
        "cpu_threads" => Some((0.0, 64.0)),
        "beam_size" => Some((1.0, 10.0)),
        "min_seconds" => Some((0.1, 5.0)),
        "silence_peak" => Some((0.0, 0.2)),
        "paste_delay_ms" => Some((0.0, 1000.0)),
        "idle_seconds" => Some((0.0, 3600.0)),
        "last_update_check" => Some((0.0, f64::MAX)),
        _ => None,
    }
}

fn coerce(key: &str, default: &Value, value: &Value) -> Value {
    if default.is_boolean() {
        if let Some(text) = value.as_str() {
            return serde_json::json!(matches!(
                text.trim().to_ascii_lowercase().as_str(),
                "true" | "1" | "yes" | "on"
            ));
        }
        return serde_json::json!(value.as_bool().unwrap_or(false));
    }
    if let (Some(range), Some(number)) = (range_for(key), value.as_f64()) {
        let clamped = number.clamp(range.0, range.1);
        if key == "min_seconds" || key == "silence_peak" || key == "last_update_check" {
            return serde_json::json!(clamped);
        }
        if default.is_f64() {
            return serde_json::json!(clamped);
        }
        if default.is_i64() || default.is_u64() {
            let as_u32 = u32::try_from(clamped.round() as i64).unwrap_or(0);
            if key == "isolate_output_level" {
                return serde_json::json!(quiet_step(as_u32));
            }
            return serde_json::json!(as_u32);
        }
    }
    if let Some(numbers) = default.as_array() {
        // Only the word-replacement list is editable; keep it well formed.
        if key == "replacements" {
            if let Some(items) = value.as_array() {
                let kept: Vec<Value> = items
                    .iter()
                    .filter(|item| {
                        item.get("find")
                            .and_then(Value::as_str)
                            .map(|f| !f.trim().is_empty())
                            .unwrap_or(false)
                    })
                    .map(|item| {
                        serde_json::json!({
                            "find": item.get("find").and_then(Value::as_str).unwrap_or(""),
                            "replace": item.get("replace").and_then(Value::as_str).unwrap_or(""),
                        })
                    })
                    .collect();
                return serde_json::json!(kept);
            }
            return serde_json::json!(numbers.clone());
        }
        return value.clone();
    }
    if default.is_string() {
        let text = value.as_str().unwrap_or_default().to_string();
        if let Some((_, options)) = CHOICES.iter().find(|(name, _)| *name == key) {
            if !options.contains(&text.as_str()) {
                return default.clone();
            }
        }
        return serde_json::json!(text);
    }
    value.clone()
}

#[derive(Debug, Clone)]
pub struct Config {
    pub path: PathBuf,
    data: Value,
}

impl Config {
    pub fn default_path() -> PathBuf {
        // A distinct folder: the installed Python app keeps %APPDATA%\FreeDictate
        // and the Rust build must never rewrite its settings.
        std::env::var("APPDATA")
            .map(|appdata| {
                PathBuf::from(appdata)
                    .join("FreeDictate-Rust")
                    .join("settings.json")
            })
            .unwrap_or_else(|_| PathBuf::from("settings.json"))
    }

    pub fn new(path: PathBuf) -> Self {
        Self {
            path,
            data: serde_json::from_str(DEFAULTS).expect("default config is valid json"),
        }
    }

    pub fn load() -> Self {
        Self::load_from(Self::default_path())
    }

    pub fn load_from(path: PathBuf) -> Self {
        let mut cfg = Self::new(path.clone());
        if let Ok(text) = std::fs::read_to_string(&path) {
            if let Ok(saved) = serde_json::from_str::<Value>(&text) {
                let defaults = cfg.data.clone();
                if let (Some(base), Some(saved)) = (cfg.data.as_object_mut(), saved.as_object()) {
                    for (key, value) in saved {
                        if let Some(default) = defaults.get(key) {
                            base.insert(key.clone(), coerce(key, default, value));
                        }
                    }
                }
            }
        }
        cfg
    }

    pub fn save(&self) -> std::io::Result<()> {
        if let Some(parent) = self.path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let text = serde_json::to_string_pretty(&self.data)? + "\n";
        let tmp = self.path.with_extension("json.tmp");
        std::fs::write(&tmp, text)?;
        std::fs::rename(tmp, &self.path)?;
        Ok(())
    }

    pub fn update(&mut self, values: &Value) {
        let defaults = self.data.clone();
        if let (Some(base), Some(new)) = (self.data.as_object_mut(), values.as_object()) {
            for (key, value) in new {
                if let Some(default) = defaults.get(key) {
                    base.insert(key.clone(), coerce(key, default, value));
                }
            }
        }
    }

    pub fn get(&self, key: &str) -> Option<&Value> {
        self.data.get(key)
    }

    pub fn bool_value(&self, key: &str) -> bool {
        self.get(key).and_then(Value::as_bool).unwrap_or(false)
    }

    pub fn number_value(&self, key: &str) -> u32 {
        self.get(key)
            .and_then(Value::as_u64)
            .and_then(|v| u32::try_from(v).ok())
            .unwrap_or(0)
    }

    pub fn float_value(&self, key: &str) -> f64 {
        self.get(key).and_then(Value::as_f64).unwrap_or(0.0)
    }

    pub fn string_value(&self, key: &str) -> String {
        self.get(key)
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string()
    }
}
