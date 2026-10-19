use std::path::PathBuf;

use serde_json::Value;

pub const DEFAULTS: &str = r#"{
  "hotkey": "ctrl+win",
  "hotkey_mode": "hold",
  "cancel_key": "esc",
  "input_device": "",
  "sounds": true,
  "sound_volume": 50,
  "mic_privacy_while_dictating": false,
  "isolate_output_while_dictating": false,
  "isolate_output_level": 0
}"#;

#[derive(Debug, Clone)]
pub struct Config {
    pub path: PathBuf,
    data: Value,
}

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
        if default.is_u64() {
            let as_u32 = u32::try_from(clamped.round() as i64).unwrap_or(0);
            if key == "isolate_output_level" {
                return serde_json::json!(quiet_step(as_u32));
            }
            return serde_json::json!(as_u32);
        }
    }
    value.clone()
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
        _ => None,
    }
}

impl Config {
    pub fn default_path() -> PathBuf {
        std::env::var("APPDATA")
            .map(|appdata| {
                PathBuf::from(appdata)
                    .join("FreeDictate")
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

    pub fn string_value(&self, key: &str) -> String {
        self.get(key)
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string()
    }
}
