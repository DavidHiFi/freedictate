//! The fixed dropdown choices of the settings window and the pure helpers
//! behind the isolate level menu. No iced types in here, so the helpers can
//! be unit tested without building a window.
//!
//! Wording follows the Python settings page: plain sentence-case labels, no
//! decoration.

/// A dropdown item: the cfg value plus what the user sees.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Choice {
    pub key: String,
    pub label: String,
}

impl std::fmt::Display for Choice {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.label)
    }
}

/// Dropdown items out of (cfg value, shown text) pairs.
pub fn choices(pairs: &[(&str, &str)]) -> Vec<Choice> {
    pairs
        .iter()
        .map(|(key, label)| Choice {
            key: (*key).to_string(),
            label: (*label).to_string(),
        })
        .collect()
}

/// The item in a list whose key matches, if any.
pub fn select<'a>(options: &'a [Choice], key: &str) -> Option<&'a Choice> {
    options.iter().find(|c| c.key == key)
}

/// Output methods, same keys as config.py CHOICES.
pub fn output_methods() -> Vec<Choice> {
    choices(&[
        ("paste", "Paste"),
        ("paste_shift_insert", "Paste with Shift+Insert"),
        ("type", "Type"),
        ("clipboard", "Clipboard only"),
    ])
}

/// Where the model runs. The labels are the Python page's plain wording.
pub fn devices() -> Vec<Choice> {
    choices(&[
        ("auto", "Choose automatically"),
        ("cpu", "Processor"),
        ("cuda", "NVIDIA graphics card"),
    ])
}

/// ctranslate2 precision, same keys as config.py CHOICES.
pub fn compute_types() -> Vec<Choice> {
    choices(&[
        ("auto", "Automatic"),
        ("int8", "int8 (smallest)"),
        ("int8_float16", "int8 + float16 (GPU)"),
        ("float16", "float16 (GPU)"),
        ("float32", "float32 (largest)"),
    ])
}

/// Speaking languages, in the order and wording of models.py LANGUAGES.
pub const LANGUAGES: &[(&str, &str)] = &[
    ("auto", "Detect automatically"),
    ("en", "English"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("de", "German"),
    ("it", "Italian"),
    ("pt", "Portuguese"),
    ("nl", "Dutch"),
    ("pl", "Polish"),
    ("ru", "Russian"),
    ("uk", "Ukrainian"),
    ("tr", "Turkish"),
    ("ar", "Arabic"),
    ("hi", "Hindi"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("zh", "Chinese"),
    ("sv", "Swedish"),
    ("da", "Danish"),
    ("no", "Norwegian"),
    ("fi", "Finnish"),
    ("cs", "Czech"),
    ("el", "Greek"),
    ("he", "Hebrew"),
    ("id", "Indonesian"),
    ("vi", "Vietnamese"),
    ("th", "Thai"),
    ("ro", "Romanian"),
    ("hu", "Hungarian"),
];

/// How long a press-to-start take may sit quiet before it ends
/// (settings.py _page_dictation, the auto_stop_silence dropdown).
pub fn auto_stop_options() -> Vec<Choice> {
    choices(&[
        ("0", "Never"),
        ("2", "After 2 seconds"),
        ("3", "After 3 seconds"),
        ("5", "After 5 seconds"),
        ("8", "After 8 seconds"),
    ])
}

/// "Keep models loaded for" (settings.py idle combo): the seconds each
/// step stores and its label; 0 means instant unload after a take.
pub fn idle_seconds_options() -> Vec<Choice> {
    choices(&[
        ("0", "Right after each take"),
        ("30", "30 seconds"),
        ("60", "1 minute"),
        ("120", "2 minutes"),
        ("300", "5 minutes"),
        ("600", "10 minutes"),
        ("1800", "30 minutes"),
        ("3600", "1 hour"),
    ])
}

/// "Delete dictations older than" (settings.py keeping-history combo);
/// 0 means keep forever.
pub fn history_days_options() -> Vec<Choice> {
    choices(&[
        ("0", "Forever"),
        ("365", "1 year"),
        ("90", "90 days"),
        ("30", "30 days"),
        ("7", "7 days"),
        ("1", "1 day"),
    ])
}

/// The three silence levels of isolate_output_level, again the Python
/// wording: "Go silent" (0), "Drop to 25%" (25), "Drop to 50%" (50).
pub fn level_options() -> Vec<Choice> {
    choices(&[("0", "Go silent"), ("25", "Drop to 25%"), ("50", "Drop to 50%")])
}

/// Menu text for a saved level. 0, 25 and 50 have direct names; any other
/// value can only reach the menu through an old settings file, and snaps to
/// the nearest of the three.
pub fn level_menu_string(level: u32) -> &'static str {
    match level {
        0 => "Go silent",
        25 => "Drop to 25%",
        50 => "Drop to 50%",
        other => {
            let distances = [other.abs_diff(0), other.abs_diff(25), other.abs_diff(50)];
            let best = distances
                .iter()
                .enumerate()
                .min_by_key(|(_, d)| **d)
                .map(|(index, _)| index)
                .unwrap_or(0);
            match best {
                1 => "Drop to 25%",
                2 => "Drop to 50%",
                _ => "Go silent",
            }
        }
    }
}

/// The stored level for a menu choice key.
pub fn level_from_choice(choice: &str) -> u32 {
    match choice {
        "25" => 25,
        "50" => 50,
        _ => 0,
    }
}

/// The choice matching a saved level, for showing the menu selection. Off-the
/// menu values snap like level_menu_string.
pub fn level_selected(level: u32) -> Choice {
    let key = match level {
        25 => "25",
        50 => "50",
        other => {
            let distances = [other.abs_diff(0), other.abs_diff(25), other.abs_diff(50)];
            let best = distances
                .iter()
                .enumerate()
                .min_by_key(|(_, d)| **d)
                .map(|(index, _)| index)
                .unwrap_or(0);
            match best {
                1 => "25",
                2 => "50",
                _ => "0",
            }
        }
    };
    Choice {
        key: key.to_string(),
        label: level_menu_string(level).to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn named_levels_map_to_their_labels() {
        assert_eq!(level_menu_string(0), "Go silent");
        assert_eq!(level_menu_string(25), "Drop to 25%");
        assert_eq!(level_menu_string(50), "Drop to 50%");
    }

    #[test]
    fn unusual_levels_snap_to_the_nearest_choice() {
        assert_eq!(level_menu_string(12), "Go silent");
        assert_eq!(level_menu_string(33), "Drop to 25%");
        assert_eq!(level_menu_string(72), "Drop to 50%");
        assert_eq!(level_selected(33).key, "25");
    }

    #[test]
    fn auto_stop_steps_carry_their_seconds() {
        let steps = auto_stop_options();
        assert_eq!(steps[0].key, "0");
        assert_eq!(steps[0].label, "Never");
        assert_eq!(steps.last().unwrap().key, "8");
        assert!(select(&steps, "5").is_some());
    }
}
