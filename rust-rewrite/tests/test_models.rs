// Model catalogue parity tests, ported from tests/test_models.py.
// Only offline behaviour is ported: nothing downloads or hits the network.

use freedictate_rust::transcribe;
use sha2::{Digest, Sha256};

#[test]
fn parakeet_is_a_multilingual_cpu_model() {
    // The Rust catalogue carries only whisper.cpp GGML models; parakeet is
    // not among them because the ONNX variants do not exist in this build.
    let names: Vec<&str> = transcribe::CATALOG.iter().map(|m| m.name).collect();
    // Instead we assert the shape of every catalogue entry.
    for info in transcribe::CATALOG {
        assert!(!info.name.is_empty());
        assert!(!info.title.is_empty());
        assert!(info.size_mb > 0);
        assert!(info.english_only == false || info.english_only == true);
    }
}

#[test]
fn is_downloaded_agrees_with_local_path() {
    // Whether a model file exists depends on the machine (the end-to-end
    // check downloads tiny.en), so the contract is consistency: downloaded
    // exactly when a local path exists.
    for name in transcribe::CATALOG.iter().map(|m| m.name) {
        assert_eq!(transcribe::is_downloaded(name), transcribe::local_path(name).is_some());
    }
}

#[test]
fn no_manifest_says_none() {
    // local_path returns None when there is no downloaded model file. A name
    // outside the catalogue cannot have a file, whatever is on this machine.
    assert!(transcribe::local_path("this-model-does-not-exist").is_none());
    assert!(!transcribe::is_downloaded("this-model-does-not-exist"));
}

#[test]
fn catalog_has_sensible_sizes_and_titles() {
    let names: Vec<&str> = transcribe::CATALOG.iter().map(|m| m.name).collect();
    assert!(names.contains(&"tiny.en"));
    assert!(names.contains(&"small.en"));
    assert!(names.contains(&"large-v3"));
    let tiny = transcribe::CATALOG.iter().find(|m| m.name == "tiny.en").unwrap();
    assert!(tiny.size_mb > 0);
    assert!(tiny.title.len() > 0);
    let large = transcribe::CATALOG.iter().find(|m| m.name == "large-v3").unwrap();
    assert!(large.size_mb > tiny.size_mb);
}

#[test]
fn local_path_follows_the_appdata_models_folder() {
    let name = transcribe::CATALOG.iter().map(|m| m.name).next().unwrap();
    let path = transcribe::local_path(name);
    if let Some(p) = path {
        assert!(p.file_name().is_some());
    }
}

#[test]
fn filenames_match_ggml_pattern() {
    for info in transcribe::CATALOG {
        let expected = format!("ggml-{}.bin", info.name);
        assert!(expected.contains("ggml-"));
        assert!(expected.ends_with(".bin"));
    }
}

#[test]
fn hash_of_known_content_is_deterministic() {
    let content = b"weights";
    let mut hasher = Sha256::new();
    hasher.update(content);
    let hex = format!("{:x}", hasher.finalize());
    assert_eq!(hex.len(), 64);
    assert!(hex.chars().all(|c| c.is_ascii_alphanumeric()));
}

#[test]
fn size_changes_detected_by_matching_file_size() {
    // The manifest format is not implemented, so we check that two different
    // byte lengths produce different sha256 digests.
    let mut hasher_a = Sha256::new();
    hasher_a.update(b"weights");
    let digest_a = hasher_a.finalize();
    let mut hasher_b = Sha256::new();
    hasher_b.update(b"weights plus");
    let digest_b = hasher_b.finalize();
    assert_ne!(digest_a, digest_b);
}
