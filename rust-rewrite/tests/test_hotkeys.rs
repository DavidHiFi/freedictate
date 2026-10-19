// Pure hotkey tests, ported from tests/test_hotkeys.py. No GetAsyncKeyState
// calls: Matcher construction is checked, held() is not (it needs a keyboard).

use freedictate_rust::hotkeys;

#[test]
fn parse_normalizes_order_and_legacy_names() {
    assert_eq!(hotkeys::normalize("win+ctrl"), "ctrl+win");
    assert_eq!(hotkeys::normalize("right-ctrl"), "rctrl");
    assert_eq!(hotkeys::normalize("right-alt"), "ralt");
    assert_eq!(hotkeys::normalize("control"), "ctrl");
    assert_eq!(hotkeys::normalize("windows"), "win");
    assert_eq!(hotkeys::normalize("Shift + Ctrl + F12"), "ctrl+shift+f12");
}

#[test]
fn invalid_inputs_fail() {
    for bad in [
        "",
        "ctrl+ctrl",
        "ctrl+nope",
        "+",
        "ctrl+mice",
        "MOUSE4+mouse4",
    ] {
        assert!(!hotkeys::is_valid(bad), "{bad:?} must be invalid");
        assert!(hotkeys::parse(bad).is_err(), "{bad:?} must not parse");
        assert_eq!(hotkeys::normalize(bad), "");
    }
}

#[test]
fn labels() {
    assert_eq!(hotkeys::label("ctrl+win"), "Ctrl + Win");
    assert_eq!(hotkeys::label("mouse4"), "Mouse back");
    assert_eq!(hotkeys::label("capslock"), "Caps Lock");
    assert_eq!(hotkeys::label("num5"), "Num 5");
    // Unparseable text comes back unchanged, like label() in hotkeys.py.
    assert_eq!(hotkeys::label("nope"), "nope");
}

#[test]
fn sort_keys_modifiers_first_then_plain() {
    assert_eq!(
        hotkeys::sort_keys(&["f12", "shift", "ctrl"]),
        ["ctrl", "shift", "f12"]
            .iter()
            .map(|s| s.to_string())
            .collect::<Vec<_>>()
    );
    assert_eq!(hotkeys::normalize("v+rctrl"), "rctrl+v");
    // rwin sits in ORDER, so it comes before any plain letter.
    assert_eq!(hotkeys::normalize("x+rwin+a"), "rwin+a+x");
}

#[test]
fn key_table_covers_the_whole_python_table() {
    // Side-specific modifiers point at one vk each; generic ones at both.
    let m = hotkeys::Matcher::new("ctrl+win");
    assert_eq!(m.text, "ctrl+win");
    assert_eq!(m.groups, [vec![0xA2u32, 0xA3], vec![0x5B, 0x5C]].to_vec());
    let r = hotkeys::Matcher::new("rctrl");
    assert_eq!(r.groups, vec![vec![0xA3u32]]);
    // F-keys, letters, digits and the numpad all parse.
    for name in [
        "f1",
        "f24",
        "f9",
        "a",
        "z",
        "0",
        "9",
        "num0",
        "num9",
        "space",
        "backquote",
        "scrolllock",
        "apps",
    ] {
        assert!(hotkeys::is_valid(name), "{name} must be a known key");
    }
    // An invalid matcher never fires: groups are empty, held() is false,
    // so a broken settings value cannot wedge the poll loop open.
    assert!(hotkeys::Matcher::new("").groups.is_empty());
    assert!(!hotkeys::Matcher::new("").held());
}

#[test]
fn matcher_rejects_unknown_keys_but_stays_constructible() {
    let m = hotkeys::Matcher::new("ctrl+nope");
    assert!(m.groups.is_empty());
    assert_eq!(m.text, "ctrl+nope");
}

#[test]
fn warnings_match_python() {
    assert_eq!(hotkeys::warning("ctrl+win"), "");
    assert!(hotkeys::warning("mouse4").to_lowercase().contains("mouse"));
    assert!(hotkeys::warning("mouse3").contains("mouse"));
    assert!(!hotkeys::warning("a").is_empty());
    assert!(!hotkeys::warning("5").is_empty());
    assert!(!hotkeys::warning("space").is_empty());
    // Modifiers alone, and function keys, carry no warning.
    assert_eq!(hotkeys::warning("rctrl"), "");
    assert_eq!(hotkeys::warning("f9"), "");
}

#[test]
fn swallowable_and_register_args_match_python() {
    assert!(hotkeys::single_key_is_swallowable("ctrl+shift+f12"));
    assert!(hotkeys::single_key_is_swallowable("capslock"));
    // Mouse buttons still do their normal job: not swallowable.
    assert!(!hotkeys::single_key_is_swallowable("mouse4"));
    // Modifier-only combos have no plain key to register.
    assert!(!hotkeys::single_key_is_swallowable("ctrl+alt"));
    let (mods, vk) = hotkeys::register_args("ctrl+shift+f12").unwrap();
    assert_eq!(vk, 0x7B);
    assert_eq!(mods & 0x2, 0x2);
    assert_eq!(mods & 0x4, 0x4);
    // MOD_NOREPEAT is always set, as in hotkeys.py.
    assert_eq!(mods & 0x4000, 0x4000);
    // ctrl+win has no plain key: RegisterHotKey cannot express it.
    assert!(hotkeys::register_args("ctrl+win").is_none());
    // Mouse buttons cannot be registered either.
    assert!(hotkeys::register_args("mouse4").is_none());
}

#[test]
fn overlaps_share_a_physical_key() {
    assert!(hotkeys::overlaps("ctrl+win", "lctrl"));
    assert!(hotkeys::overlaps("f9", "f9"));
    // Generic "win" matches either side: both share the left Win vk.
    assert!(hotkeys::overlaps("ctrl+win", "alt+win"));
    assert!(!hotkeys::overlaps("f9", "esc"));
    assert!(!hotkeys::overlaps("bad text", "ctrl"));
}

#[test]
fn generalize_keeps_a_lone_side_specific_modifier() {
    assert_eq!(hotkeys::generalize(&["rctrl"]), ["rctrl".to_string()]);
    assert_eq!(
        hotkeys::generalize(&["lctrl", "lwin"]),
        ["ctrl".to_string(), "win".to_string()]
    );
    assert_eq!(
        hotkeys::generalize(&["lctrl", "lshift", "f12"]),
        ["ctrl".to_string(), "shift".to_string(), "f12".to_string()]
    );
    assert_eq!(hotkeys::generalize(&["ralt", "lalt"]), ["alt".to_string()]);
    // The generic lone Win (from rwin) sorts before the letter.
    assert_eq!(
        hotkeys::generalize(&["v", "rwin"]),
        ["win".to_string(), "v".to_string()]
    );
}
