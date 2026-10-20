// Parse + behavior for the saved word-replacement list, mirroring tests
// that would cover _replacements() / apply_replacements() in textproc.py.

use freedictate_rust::textproc::{
    apply_replacements, clean, replacements_from_config, Options, Replacement,
};
use serde_json::{json, Value};

fn parse(v: Value) -> Vec<Replacement> {
    replacements_from_config(Some(&v))
}

#[test]
fn parses_config_shape() {
    let pairs = parse(json!([{"find": "gpu", "replace": "graphics card"}]));
    assert_eq!(pairs.len(), 1);
    assert_eq!(pairs[0].find, "gpu");
    assert_eq!(pairs[0].replace, "graphics card");
}

#[test]
fn skips_malformed_entries() {
    let pairs = parse(json!([
        {"find": "  ", "replace": "kept"},        // blank find after trim
        {"replace": "no find key"},
        {"find": 42},                              // non-string find
        7,                                         // not an object at all
        {"find": " ok ", "replace": "fine"},
    ]));
    assert_eq!(pairs.len(), 1, "only the well-formed pair survives");
    assert_eq!(pairs[0].find, "ok");
    assert_eq!(pairs[0].replace, "fine");
}

#[test]
fn missing_replace_means_empty() {
    let pairs = parse(json!([{"find": "uh"}]));
    assert_eq!(pairs.len(), 1);
    assert_eq!(pairs[0].replace, "");
}

#[test]
fn non_array_is_empty() {
    assert!(parse(json!({})).is_empty());
    assert!(parse(json!("x")).is_empty());
    assert!(replacements_from_config(None).is_empty());
}

#[test]
fn whole_word_case_insensitive() {
    let pairs = parse(json!([
        {"find": "foo", "replace": "bar"},
        {"find": "rev", "replace": "revision"}
    ]));
    // Whole-word matching: "Foodbar" and "REVS" contain no standalone hits.
    assert_eq!(apply_replacements("The Foodbar and the REVS.", &pairs), "The Foodbar and the REVS.");
    assert_eq!(apply_replacements("The foo FOO and the rev REV.", &pairs),
        "The bar bar and the revision revision.");
}

#[test]
fn unicode_find_is_word_boundaried() {
    let pairs = parse(json!([{"find": "müller", "replace": "Mueller"}]));
    assert_eq!(apply_replacements("müllers street", &pairs), "müllers street");
    assert_eq!(apply_replacements("hello müller", &pairs), "hello Mueller");
}

#[test]
fn runs_twice_inside_clean() {
    // Spoken punctuation runs after the first pass, so a find that only
    // exists once "dash dash" became " - " still applies (each spoken dash
    // becomes its own " - ").
    let opts = Options {
        voice_commands: true,
        ..Options::default()
    };
    let pairs = parse(json!([{"find": "-", "replace": "(dash)"}]));
    let mut o = opts.clone();
    o.replacements = pairs.clone();
    let text = clean("hello dash dash world", &o);
    assert_eq!(text, "Hello (dash) (dash) world.");
}

#[test]
fn empty_config_changes_nothing() {
    let opts = Options::default(); // replacements empty
    assert_eq!(clean("Hello world", &opts), "Hello world.");
}
