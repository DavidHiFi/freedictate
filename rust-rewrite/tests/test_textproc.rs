// Port of tests/test_textproc.py
// Tests for textproc module: clean, detect_submit, word_count

use freedictate_rust::textproc::{clean, detect_submit, word_count, Options, Replacement};

fn default_opts() -> Options {
    Options::default()
}

#[test]
fn test_removes_fillers_and_capitalizes() {
    let opts = Options {
        remove_fillers: true,
        voice_commands: true,
        capitalize: true,
        end_punctuation: true,
        repeats: false,
        replacements: vec![],
        language: Some("en".to_string()),
    };
    assert_eq!(clean("um so I think uh we should go", &opts), "So I think we should go.");
}

#[test]
fn test_keeps_meaningful_words() {
    let opts = default_opts();
    assert_eq!(clean("I like it, you know", &opts), "I like it, you know.");
}

#[test]
fn test_voice_commands_keep_the_speakers_punctuation() {
    let opts = default_opts();
    assert_eq!(
        clean("Dear John, new line. Thanks for the note. New paragraph. Best", &opts),
        "Dear John,\nThanks for the note.\n\nBest."
    );
}

#[test]
fn test_voice_commands_off_leaves_words() {
    let opts = Options {
        voice_commands: false,
        ..default_opts()
    };
    assert_eq!(clean("type new line here", &opts), "Type new line here.");
}

#[test]
fn test_replacements_match_whole_words_any_case() {
    let reps = vec![
        Replacement { find: "api".to_string(), replace: "API".to_string() },
        Replacement { find: "free dictate".to_string(), replace: "FreeDictate".to_string() },
    ];
    let opts = Options {
        replacements: reps,
        ..default_opts()
    };
    assert_eq!(clean("the api of free dictate rapid", &opts), "The API of FreeDictate rapid.");
}

#[test]
fn test_end_punctuation_only_when_missing() {
    let opts = default_opts();
    assert_eq!(clean("is it done?", &opts), "Is it done?");
    let opts_no_punct = Options {
        end_punctuation: false,
        ..default_opts()
    };
    assert_eq!(clean("done", &opts_no_punct), "Done");
}

#[test]
fn test_filler_only_take_is_empty() {
    let opts = default_opts();
    assert_eq!(clean("Um.", &opts), "");
    assert_eq!(clean("   ", &opts), "");
}

#[test]
fn test_word_count() {
    assert_eq!(word_count("Don't stop, it's 3 o'clock."), 5);
}

#[test]
fn test_repeats_collapse_stumbles_but_keep_meaningful_doubles() {
    let opts_repeats = Options {
        repeats: true,
        ..default_opts()
    };
    assert_eq!(clean("make sure the the entire app works", &opts_repeats), "Make sure the entire app works.");
    assert_eq!(clean("I want, I want to open up my game open up my game now", &opts_repeats), "I want to open up my game now.");
    assert_eq!(clean("The the cat sat", &opts_repeats), "The cat sat.");
    assert_eq!(clean("really really quickly, they had had enough", &opts_repeats), "Really really quickly, they had had enough.");
    assert_eq!(clean("what it is is fine", &opts_repeats), "What it is is fine.");
    let opts_no_repeats = Options {
        repeats: false,
        ..default_opts()
    };
    assert_eq!(clean("the the cat", &opts_no_repeats), "The the cat.");
}

#[test]
fn test_repeats_stop_at_a_sentence_end() {
    let opts_repeats = Options {
        repeats: true,
        ..default_opts()
    };
    assert_eq!(clean("Go home. Go home now", &opts_repeats), "Go home. Go home now.");
}

#[test]
fn test_spoken_punctuation_replaces_whispers_guess() {
    let opts = default_opts();
    assert_eq!(
        clean("Hello, comma, how are you question mark? I'm fine full stop. thanks", &opts),
        "Hello, how are you? I'm fine. Thanks."
    );
    assert_eq!(clean("well hyphen known file underscore name", &opts), "Well-known file_name.");
    assert_eq!(
        clean("open bracket optional close bracket and open quote hi there close quote said", &opts),
        "(optional) and \"hi there\" said."
    );
}

#[test]
fn test_spoken_dot_points_build_a_list() {
    let opts = default_opts();
    assert_eq!(
        clean("my shopping list colon dot point milk dot point eggs dot point bread", &opts),
        "My shopping list:\n- Milk\n- Eggs\n- Bread"
    );
    assert_eq!(
        clean("Things to do. New line. Dot point fix it", &opts),
        "Things to do.\n- Fix it"
    );
    assert_eq!(
        clean("Intro new paragraph dot point a dot point b", &opts),
        "Intro\n\n- A\n- B"
    );
}

#[test]
fn test_literal_types_the_word() {
    let opts = default_opts();
    assert_eq!(clean("type literal comma here and a comma here", &opts), "Type comma here and a, here.");
}

#[test]
fn test_words_containing_commands_are_untouched() {
    let opts = default_opts();
    assert_eq!(clean("the dashboard has a colonnade", &opts), "The dashboard has a colonnade.");
}

#[test]
fn test_portuguese_and_german_keep_um() {
    let mut opts = default_opts();
    opts.language = Some("pt".to_string());
    assert_eq!(clean("Faça um commit", &opts), "Faça um commit.");
    opts.language = Some("pt-BR".to_string());
    assert_eq!(clean("Faça um commit", &opts), "Faça um commit.");
    opts.language = Some("de_DE".to_string());
    assert_eq!(clean("Gehen wir um die Ecke", &opts), "Gehen wir um die Ecke.");
}

#[test]
fn test_english_and_unknown_still_drop_um() {
    let mut opts = default_opts();
    opts.language = Some("en".to_string());
    assert_eq!(clean("so um let us commit", &opts), "So let us commit.");
    opts.language = None;
    assert_eq!(clean("so um let us commit", &opts), "So let us commit.");
}

#[test]
fn test_filler_cleanup_leaves_no_dangling_connectors() {
    let opts = default_opts();
    assert_eq!(clean("hello world, uh.", &opts), "Hello world.");
    assert_eq!(clean("hello world, um", &opts), "Hello world.");
    assert_eq!(clean("hello, uh, world", &opts), "Hello, world.");
    let opts_no_punct = Options {
        end_punctuation: false,
        ..default_opts()
    };
    assert_eq!(clean("hello world, uh", &opts_no_punct), "Hello world");
}

#[test]
fn test_replacements_run_again_after_voice_commands() {
    // Pass one cannot match: "dash" is still a word. Only after spoken
    // punctuation turns it into " - " does the find become matchable.
    let reps = vec![Replacement { find: "-".to_string(), replace: "–".to_string() }];
    let opts = Options {
        replacements: reps,
        ..default_opts()
    };
    assert_eq!(clean("hello dash world", &opts), "Hello – world.");
}

#[test]
fn test_spacing_tidy_around_punctuation() {
    let opts = default_opts();
    assert_eq!(clean("call open paren x , y close paren now", &opts), "Call (x, y) now.");
    assert_eq!(clean("wait , then go", &opts), "Wait, then go.");
    // List markers and newlines survive the tidy.
    assert_eq!(
        clean("things to do. new line. dot point fix it , fast", &opts),
        "Things to do.\n- Fix it, fast"
    );
}

#[test]
fn test_detect_submit_strips_and_fires() {
    assert_eq!(detect_submit("hello world submit"), ("hello world".to_string(), true));
    assert_eq!(detect_submit("hello world submit."), ("hello world".to_string(), true));
    assert_eq!(detect_submit("hello world SUBMIT!"), ("hello world".to_string(), true));
    assert_eq!(detect_submit("hello world, submit"), ("hello world".to_string(), true));
}

#[test]
fn test_detect_submit_keeps_sentence_punctuation() {
    assert_eq!(detect_submit("hello world. submit"), ("hello world.".to_string(), true));
}

#[test]
fn test_detect_submit_ignores_other_uses() {
    assert_eq!(detect_submit("submit this please"), ("submit this please".to_string(), false));
    assert_eq!(detect_submit("I need to pre-submit"), ("I need to pre-submit".to_string(), false));
    assert_eq!(detect_submit("hello world"), ("hello world".to_string(), false));
    assert_eq!(detect_submit("submit"), ("".to_string(), true));
}