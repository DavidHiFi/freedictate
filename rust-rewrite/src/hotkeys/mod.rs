//! Hotkey parsing, matching and display. Port of hotkeys.py.
//!
//! A hotkey is a `+`-joined list of key names, e.g. `ctrl+win` or `rctrl` or
//! `ctrl+shift+space`. Generic modifier names match either side. Keys are read
//! by polling `GetAsyncKeyState`: Windows silently drops a low-level keyboard
//! hook whose callback stalls, which once left v1 running but deaf. Polling
//! cannot fail that way.

use std::collections::HashMap;
use std::sync::OnceLock;

use windows::Win32::UI::Input::KeyboardAndMouse::GetAsyncKeyState;

struct KeyEntry {
    name: &'static str,
    label: &'static str,
    // Virtual-key codes that count as this key.
    vks: &'static [u32],
}

/// Built in the same order as the KEYS dict in hotkeys.py: base keys, then
/// F1..F24, then letters, digits and the numpad. Order only matters for
/// building the most-specific-name map used while recording.
static KEYS_TABLE: OnceLock<Vec<KeyEntry>> = OnceLock::new();

fn table() -> &'static [KeyEntry] {
    KEYS_TABLE.get_or_init(build_table)
}

// The fixed VK lists are leaked once at first use so key entries can hold them.
fn vks(list: &[u32]) -> &'static [u32] {
    Box::leak(list.to_vec().into_boxed_slice())
}

fn build_table() -> Vec<KeyEntry> {
    let mut out: Vec<KeyEntry> = Vec::new();
    let mut add = |name: &'static str, label: &'static str, codes: &[u32]| {
        out.push(KeyEntry {
            name,
            label,
            vks: vks(codes),
        });
    };
    add("ctrl", "Ctrl", &[0xA2, 0xA3]);
    add("lctrl", "Left Ctrl", &[0xA2]);
    add("rctrl", "Right Ctrl", &[0xA3]);
    add("alt", "Alt", &[0xA4, 0xA5]);
    add("lalt", "Left Alt", &[0xA4]);
    add("ralt", "Right Alt", &[0xA5]);
    add("shift", "Shift", &[0xA0, 0xA1]);
    add("lshift", "Left Shift", &[0xA0]);
    add("rshift", "Right Shift", &[0xA1]);
    add("win", "Win", &[0x5B, 0x5C]);
    add("lwin", "Left Win", &[0x5B]);
    add("rwin", "Right Win", &[0x5C]);
    add("space", "Space", &[0x20]);
    add("tab", "Tab", &[0x09]);
    add("capslock", "Caps Lock", &[0x14]);
    add("esc", "Esc", &[0x1B]);
    add("enter", "Enter", &[0x0D]);
    add("backspace", "Backspace", &[0x08]);
    add("insert", "Insert", &[0x2D]);
    add("delete", "Delete", &[0x2E]);
    add("home", "Home", &[0x24]);
    add("end", "End", &[0x23]);
    add("pageup", "Page Up", &[0x21]);
    add("pagedown", "Page Down", &[0x22]);
    add("up", "Up", &[0x26]);
    add("down", "Down", &[0x28]);
    add("left", "Left", &[0x25]);
    add("right", "Right", &[0x27]);
    add("pause", "Pause", &[0x13]);
    add("scrolllock", "Scroll Lock", &[0x91]);
    add("apps", "Menu", &[0x5D]);
    add("backquote", "`", &[0xC0]);
    add("minus", "-", &[0xBD]);
    add("equals", "=", &[0xBB]);
    add("lbracket", "[", &[0xDB]);
    add("rbracket", "]", &[0xDD]);
    add("backslash", "\\", &[0xDC]);
    add("semicolon", ";", &[0xBA]);
    add("quote", "'", &[0xDE]);
    add("comma", ",", &[0xBC]);
    add("period", ".", &[0xBE]);
    add("slash", "/", &[0xBF]);
    add("mouse3", "Middle mouse", &[0x04]);
    add("mouse4", "Mouse back", &[0x05]);
    add("mouse5", "Mouse forward", &[0x06]);
    for i in 1..=25u8 {
        let vks = vks(&[0x6F + u32::from(i)]);
        out.push(KeyEntry {
            name: leaked_str(&format!("f{i}")),
            label: leaked_str(&format!("F{i}")),
            vks,
        });
    }
    for c in b'a'..=b'z' {
        let upper = c.to_ascii_uppercase() as u32;
        let name = leaked_str(std::str::from_utf8(&[c]).unwrap_or("a"));
        let label = leaked_str(std::str::from_utf8(&[c.to_ascii_uppercase()]).unwrap_or("A"));
        out.push(KeyEntry {
            name,
            label,
            vks: vks(&[upper]),
        });
    }
    for c in b'0'..=b'9' {
        let buf = [c];
        let s = std::str::from_utf8(&buf).unwrap_or("0");
        out.push(KeyEntry {
            name: leaked_str(s),
            label: leaked_str(s),
            vks: vks(&[u32::from(c)]),
        });
    }
    for d in 0..10u32 {
        let codes = vks(&[0x60 + d]);
        out.push(KeyEntry {
            name: leaked_str(&format!("num{d}")),
            label: leaked_str(&format!("Num {d}")),
            vks: codes,
        });
    }
    out
}

// The generated F-key and numpad names are not 'static literals; leak the
// short Strings once at first use (a few hundred bytes for the app lifetime).
fn leaked_str(s: &str) -> &'static str {
    Box::leak(s.to_string().into_boxed_str())
}

pub const MODIFIERS: [&str; 12] = [
    "ctrl", "lctrl", "rctrl", "alt", "lalt", "ralt", "shift", "lshift", "rshift", "win", "lwin",
    "rwin",
];

pub const MODIFIER_VKS: [u32; 8] = [0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C];

pub const MOUSE: [&str; 3] = ["mouse3", "mouse4", "mouse5"];

pub const VK_ESCAPE: u32 = 0x1B;

/// Order used when displaying and when recording a combination.
static ORDER: [&str; 12] = [
    "ctrl", "lctrl", "rctrl", "win", "lwin", "rwin", "alt", "lalt", "ralt", "shift", "lshift",
    "rshift",
];

pub const PRESETS: [&str; 8] = [
    "ctrl+win",
    "ctrl+alt",
    "ctrl+shift",
    "rctrl",
    "ralt",
    "capslock",
    "f9",
    "mouse4",
];

/// vk -> most specific name, for recording a new hotkey with keys_down_now().
static VK_NAME: OnceLock<HashMap<u32, &'static str>> = OnceLock::new();

fn vk_name() -> &'static HashMap<u32, &'static str> {
    VK_NAME.get_or_init(|| {
        let mut map = HashMap::new();
        for entry in table() {
            // Sided names come first in the table, so they win over "ctrl"/"win".
            if entry.vks.len() == 1 {
                map.entry(entry.vks[0]).or_insert(entry.name);
            }
        }
        map
    })
}

fn find(name: &str) -> Option<&'static KeyEntry> {
    table().iter().find(|k| k.name == name)
}

fn order_index(name: &str) -> usize {
    ORDER.iter().position(|o| *o == name).unwrap_or(100)
}

fn is_modifier(name: &str) -> bool {
    MODIFIERS.contains(&name)
}

/// Sorted key names in display order. Modifiers first (in ORDER), then the
/// plain key alphabetically.
pub fn sort_keys(names: &[&str]) -> Vec<String> {
    let mut out: Vec<String> = names.iter().map(|s| (*s).to_string()).collect();
    out.sort_by(|a, b| (order_index(a), a.as_str()).cmp(&(order_index(b), b.as_str())));
    out
}

/// Parse and validate a hotkey string; Err for unknown keys, duplicates
/// and empty lists.
pub fn parse(text: &str) -> Result<Vec<String>, String> {
    let compact = text.replace(' ', "");
    let mut parts: Vec<String> = Vec::new();
    for piece in compact.split('+') {
        let p = piece.trim().to_ascii_lowercase();
        if p.is_empty() {
            continue;
        }
        // Legacy spellings from the settings text.
        let p = match p.as_str() {
            "right-ctrl" => "rctrl".to_string(),
            "right-alt" => "ralt".to_string(),
            "control" => "ctrl".to_string(),
            "windows" => "win".to_string(),
            other => other.to_string(),
        };
        parts.push(p);
    }
    let ok = !parts.is_empty()
        && parts.iter().all(|p| find(p).is_some())
        && parts.iter().collect::<std::collections::HashSet<_>>().len() == parts.len();
    if !ok {
        return Err(format!("Unknown hotkey: {text:?}"));
    }
    let refs: Vec<&str> = parts.iter().map(|s| s.as_str()).collect();
    Ok(sort_keys(&refs))
}

pub fn normalize(text: &str) -> String {
    parse(text).map(|parts| parts.join("+")).unwrap_or_default()
}

/// Display form, e.g. "Ctrl + Win"; the raw text back when it does not parse.
pub fn label(text: &str) -> String {
    match parse(text) {
        Ok(parts) => parts
            .iter()
            .filter_map(|p| find(p).map(|k| k.label.to_string()))
            .collect::<Vec<_>>()
            .join(" + "),
        Err(_) => text.to_string(),
    }
}

pub fn is_valid(text: &str) -> bool {
    parse(text).is_ok()
}

/// True when the two shortcuts share a physical key, so holding one holds the other.
pub fn overlaps(a: &str, b: &str) -> bool {
    let keys_a: Vec<u32> = parse(a)
        .ok()
        .map(|names| vks_of(&names))
        .unwrap_or_default();
    let keys_b: Vec<u32> = parse(b)
        .ok()
        .map(|names| vks_of(&names))
        .unwrap_or_default();
    keys_a.iter().any(|vk| keys_b.contains(vk))
}

fn vks_of(names: &[String]) -> Vec<u32> {
    names
        .iter()
        .filter_map(|n| find(n).map(|k| k.vks.to_vec()))
        .flatten()
        .collect()
}

/// A short caution for hotkeys that will also reach the focused app, or "".
pub fn warning(text: &str) -> String {
    let keys = match parse(text) {
        Ok(k) => k,
        Err(_) => return String::new(),
    };
    if keys.iter().any(|k| MOUSE.contains(&k.as_str())) {
        return "The mouse button still does its normal job, like going back in a browser."
            .to_string();
    }
    let plain: Vec<&String> = keys.iter().filter(|k| !is_modifier(k)).collect();
    if keys.len() == 1 && plain.len() == 1 {
        let k = plain[0].to_ascii_lowercase();
        let single = k.as_bytes();
        let alone =
            single.len() == 1 && (single[0].is_ascii_lowercase() || single[0].is_ascii_digit());
        if alone || k == "space" {
            return "A single letter, digit or Space would stop you from typing it. Add a modifier.".to_string();
        }
    }
    String::new()
}

/// True when RegisterHotKey can stop the key reaching other apps.
pub fn single_key_is_swallowable(text: &str) -> bool {
    let keys = match parse(text) {
        Ok(k) => k,
        Err(_) => return false,
    };
    let plain: Vec<&String> = keys.iter().filter(|k| !is_modifier(k)).collect();
    plain.len() == 1 && !MOUSE.contains(&plain[0].as_str())
}

/// (modifiers, vk) for RegisterHotKey, or None when the hotkey has no plain key.
pub fn register_args(text: &str) -> Option<(u32, u32)> {
    let keys = parse(text).ok()?;
    let plain: Vec<&String> = keys.iter().filter(|k| !is_modifier(k)).collect();
    if plain.len() != 1 || MOUSE.contains(&plain[0].as_str()) {
        return None;
    }
    let mut mods = 0x4000; // MOD_NOREPEAT
    for k in &keys {
        match k.as_str() {
            "alt" | "lalt" | "ralt" => mods |= 0x1,
            "ctrl" | "lctrl" | "rctrl" => mods |= 0x2,
            "shift" | "lshift" | "rshift" => mods |= 0x4,
            "win" | "lwin" | "rwin" => mods |= 0x8,
            _ => {}
        }
    }
    let vk = find(plain[0])?.vks[0];
    Some((mods, vk))
}

/// Live physical-key read for the poller.
pub fn key_down(vk: u32) -> bool {
    unsafe { (GetAsyncKeyState(vk as i32) as u16 & 0x8000) != 0 }
}

/// Answers "is the hotkey held right now?" for one hotkey string.
pub struct Matcher {
    pub text: String,
    pub groups: Vec<Vec<u32>>,
}

impl Matcher {
    /// Invalid hotkeys are tolerated at construction for the poller: groups
    /// stays empty and held() reports false, like a matcher that never fires.
    pub fn new(text: &str) -> Self {
        match parse(text) {
            Ok(names) => Matcher {
                text: names.join("+"),
                groups: names
                    .iter()
                    .filter_map(|n| find(n).map(|k| k.vks.to_vec()))
                    .collect(),
            },
            Err(_) => Matcher {
                text: text.to_string(),
                groups: Vec::new(),
            },
        }
    }

    pub fn held(&self) -> bool {
        !self.groups.is_empty() && self.groups.iter().all(|g| g.iter().any(|&vk| key_down(vk)))
    }
}

pub fn modifiers_down() -> bool {
    MODIFIER_VKS.iter().any(|&vk| key_down(vk))
}

/// Names of recordable keys held at this instant (side-specific for modifiers).
pub fn keys_down_now() -> Vec<String> {
    let mut names: Vec<&str> = vk_name()
        .iter()
        .filter(|(vk, _)| **vk != 0x0D)
        .filter(|(vk, _)| key_down(**vk))
        .map(|(_, name)| *name)
        .collect();
    names.sort_unstable();
    names.dedup();
    sort_keys(&names)
}

/// Left Ctrl + Left Win -> Ctrl + Win, unless only one side makes sense.
///
/// A lone modifier keeps its side (Right Ctrl), because a generic lone Ctrl
/// would fire on every Ctrl+C.
pub fn generalize(names: &[&str]) -> Vec<String> {
    if names.len() == 1 {
        return vec![names[0].to_string()];
    }
    let mut out: Vec<String> = Vec::new();
    for n in names {
        // Two-letter sided names (lctrl, rwin) become the generic modifier.
        let generic = is_modifier(n) && matches!(&n[1..], "ctrl" | "alt" | "shift" | "win");
        let n = if generic { &n[1..] } else { n };
        if !out.iter().any(|o| o == n) {
            out.push(n.to_string());
        }
    }
    let refs: Vec<&str> = out.iter().map(|s| s.as_str()).collect();
    sort_keys(&refs)
}
