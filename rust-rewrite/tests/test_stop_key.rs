// Stop-key parity tests, ported from tests/test_stop_key.py.
// The engine internals used by the stop-key tests are not public, so this
// file exercises the hotkey layer that the stop key is built on, plus the
// Config coercion of cancel_key. Anything needing GetAsyncKeyState or a live
// window is intentionally left out.

use std::path::PathBuf;

use freedictate_rust::config::Config;
use freedictate_rust::hotkeys;

#[test]
fn cancel_key_defaults_to_esc() {
    let dir = std::env::temp_dir().join("freedictate-rust-tests").join("cancel-key");
    let _ = std::fs::create_dir_all(&dir);
    let c = Config::new(dir.join("settings.json"));
    assert_eq!(c.string_value("cancel_key"), "esc");
}

#[test]
fn label_esc_is_capitalized() {
    assert_eq!(hotkeys::label("esc"), "Esc");
}

#[test]
fn overlaps_share_a_physical_key() {
    assert!(hotkeys::overlaps("ctrl+win", "lctrl"));
    assert!(hotkeys::overlaps("esc", "esc"));
    assert!(!hotkeys::overlaps("ctrl+win", "esc"));
    assert!(!hotkeys::overlaps("bad text", "ctrl"));
}

#[test]
fn parse_rejects_unknown_keys_and_duplicates() {
    assert!(hotkeys::parse("").is_err());
    assert!(hotkeys::parse("ctrl+ctrl").is_err());
    assert!(hotkeys::parse("ctrl+nope").is_err());
    assert!(hotkeys::is_valid("ctrl+win"));
    assert!(hotkeys::is_valid("esc"));
    assert!(hotkeys::is_valid("lctrl"));
}

#[test]
fn parse_normalizes_legacy_spellings() {
    assert_eq!(hotkeys::normalize("win+ctrl"), "ctrl+win");
    assert_eq!(hotkeys::normalize("right-ctrl"), "rctrl");
    assert_eq!(hotkeys::normalize("right-alt"), "ralt");
    assert_eq!(hotkeys::normalize("control"), "ctrl");
    assert_eq!(hotkeys::normalize("windows"), "win");
}

#[test]
fn matcher_text_matches_the_input() {
    let m = hotkeys::Matcher::new("ctrl+win");
    assert_eq!(m.text, "ctrl+win");
    assert_eq!(m.groups.len(), 2);
    let r = hotkeys::Matcher::new("rctrl");
    assert_eq!(r.groups.len(), 1);
}

#[test]
fn an_invalid_matcher_never_fires() {
    let m = hotkeys::Matcher::new("ctrl+nope");
    assert!(m.groups.is_empty());
    assert!(!m.held());
}

#[test]
fn single_key_is_swallowable() {
    assert!(hotkeys::single_key_is_swallowable("ctrl+shift+f12"));
    assert!(hotkeys::single_key_is_swallowable("capslock"));
    assert!(!hotkeys::single_key_is_swallowable("mouse4"));
    assert!(!hotkeys::single_key_is_swallowable("ctrl+alt"));
}

#[test]
fn register_args_have_mod_no_repeat() {
    let (mods, vk) = hotkeys::register_args("ctrl+shift+f12").unwrap();
    assert_eq!(vk, 0x7B);
    assert_eq!(mods & 0x2, 0x2);
    assert_eq!(mods & 0x4, 0x4);
    assert_eq!(mods & 0x4000, 0x4000);
    assert!(hotkeys::register_args("ctrl+win").is_none());
    assert!(hotkeys::register_args("mouse4").is_none());
}

#[test]
fn generalize_collapses_side_specific_modifiers() {
    assert_eq!(
        hotkeys::generalize(&["lctrl", "lwin"]),
        ["ctrl".to_string(), "win".to_string()]
    );
    assert_eq!(hotkeys::generalize(&["rctrl"]), ["rctrl".to_string()]);
    assert_eq!(
        hotkeys::generalize(&["ralt", "lalt"]),
        ["alt".to_string()]
    );
}
