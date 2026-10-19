// Pure catalog/directory tests for the transcribe module. No network: the
// download test is #[ignore] so a CI run never touches Hugging Face.

use freedictate_rust::transcribe;

#[test]
fn catalog_shape() {
    // Names are unique: BY_NAME maps take the first hit, duplicates would hide.
    let mut names: Vec<&str> = transcribe::CATALOG.iter().map(|m| m.name).collect();
    names.sort_unstable();
    let n = names.len();
    names.dedup();
    assert_eq!(names.len(), n, "catalog names must be unique");

    // The ggml catalog is fixed: which entries, English flags and sizes.
    let expected: &[(&str, bool, u64)] = &[
        ("tiny.en", true, 77),
        ("base.en", true, 148),
        ("small.en", true, 487),
        ("medium.en", true, 1530),
        ("large-v3-turbo", false, 1620),
        ("large-v3", false, 3090),
        ("tiny", false, 77),
        ("base", false, 148),
        ("small", false, 487),
        ("medium", false, 1530),
    ];
    assert_eq!(transcribe::CATALOG.len(), expected.len());
    for (name, english_only, size_mb) in expected.iter() {
        let m = transcribe::CATALOG
            .iter()
            .find(|m| m.name == *name)
            .unwrap_or_else(|| {
                panic!("catalog entry {name} missing");
            });
        assert_eq!(m.english_only, *english_only, "{name} english_only");
        assert_eq!(m.size_mb, *size_mb, "{name} size_mb");
        assert!(!m.title.is_empty(), "{name} needs a display title");
    }
}

#[test]
fn fallback_order_sits_at_the_small_english_models() {
    assert_eq!(
        transcribe::FALLBACK_ORDER,
        ["small.en", "base.en", "tiny.en"]
    );
    // Every fallback must be a real catalog entry.
    for name in transcribe::FALLBACK_ORDER {
        assert!(transcribe::CATALOG.iter().any(|m| *m.name == *name));
    }
}

#[test]
fn models_dir_sits_under_appdata() {
    if let Some(appdata) = std::env::var_os("APPDATA") {
        let dir = transcribe::models_dir();
        let expected = std::path::PathBuf::from(&appdata)
            .join("FreeDictate-Rust")
            .join("models");
        assert_eq!(dir, expected);
    }
}

#[test]
fn local_path_points_at_ggml_bin() {
    if std::env::var_os("APPDATA").is_some() {
        let model = transcribe::models_dir().join("ggml-tiny.en.bin");
        // Whatever the disk holds, the file path and the download flag agree.
        if transcribe::is_downloaded("tiny.en") {
            assert_eq!(
                transcribe::local_path("tiny.en").as_deref(),
                Some(model.as_path())
            );
        } else {
            assert!(transcribe::local_path("tiny.en").is_none());
        }
    }
}

#[test]
fn unknown_names_never_reach_disk() {
    assert!(transcribe::local_path("").is_none());
    assert!(transcribe::local_path("parakeet-tdt-0.6b-v2").is_none());
    assert!(transcribe::local_path("../../etc/passwd").is_none());
    assert!(!transcribe::is_downloaded("not-a-model"));
    assert!(!transcribe::is_downloaded("distil-medium.en"));
}

// Offline decode against a local model file; only meaningful when a ggml
// model is already downloaded. Run with `cargo test -- --ignored`.
#[test]
#[ignore = "needs a local ggml model file under %APPDATA%\\FreeDictate-Rust\\models"]
fn local_model_decodes_silence() {
    let Some(path) = ["tiny.en", "base.en", "small.en"]
        .iter()
        .find_map(|n| transcribe::local_path(n))
    else {
        return; // nothing downloaded on this machine
    };
    let voice = transcribe::Voice::load(&path).expect("model load");
    // One second of silence decodes to (near) nothing without failing.
    let samples = vec![0.0f32; 16000];
    let text = voice.transcribe(&samples, Some("en")).expect("decode");
    assert!(text.is_empty() || text.len() < 60, "silence gave: {text:?}");
    voice.unload();
}
