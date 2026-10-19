use std::collections::HashMap;

use freedictate_rust::updater::{self, Release, parse_version, newer, latest, check, _asset, _expected_sha};

#[test]
fn parse_version_basic() {
    let v = parse_version("3.6.1");
    assert_eq!(v, (3, 6, 1, 3, 0));
}

#[test]
fn parse_version_prerelease() {
    let v = parse_version("3.7.0-beta2");
    assert_eq!(v, (3, 7, 0, 1, 2));
}

#[test]
fn newer_detects_upgrade() {
    let a = parse_version("3.6.0");
    let b = parse_version("3.6.1");
    assert!(a < b);
    assert!(newer("3.6.1", "3.6.0"));
    assert!(!newer("3.6.0", "3.6.1"));
    assert!(!newer("3.6.1", "3.6.1"));
}

#[test]
fn prerelease_ranking() {
    assert!(newer("3.6.0-rc1", "3.6.0-beta2"));
    assert!(newer("3.6.0-rc", "3.6.0-beta"));
    assert!(newer("3.6.0-beta", "3.6.0-alpha"));
}

#[test]
fn asset_selection() {
    let mut assets = HashMap::new();
    assets.insert("FreeDictateSetup.exe".to_string(), "https://example.com/setup.exe".to_string());
    assets.insert("FreeDictate-portable.zip".to_string(), "https://example.com/portable.zip".to_string());
    let rel = Release {
        version: "3.6.1".to_string(),
        tag: "v3.6.1".to_string(),
        name: "Release 3.6.1".to_string(),
        notes: "Notes".to_string(),
        url: "https://example.com".to_string(),
        prerelease: false,
        assets,
    };
    let (name, url) = _asset(&rel, false).unwrap();
    assert_eq!(name, "FreeDictateSetup.exe");
    assert!(url.contains("setup"));
    let (name2, url2) = _asset(&rel, true).unwrap();
    assert_eq!(name2, "FreeDictate-portable.zip");
    assert!(url2.contains("portable"));
}

#[test]
fn no_matching_asset() {
    let mut assets = HashMap::new();
    assets.insert("other.exe".to_string(), "https://example.com/other.exe".to_string());
    let rel = Release {
        version: "3.6.1".to_string(),
        tag: "v3.6.1".to_string(),
        name: "Release".to_string(),
        notes: "Notes".to_string(),
        url: "https://example.com".to_string(),
        prerelease: false,
        assets,
    };
    let result = _asset(&rel, false);
    assert!(result.is_err());
}

#[test]
fn version_parsing_with_prerelease() {
    assert_eq!(parse_version("1.2.3"), (1, 2, 3, 3, 0));
    assert_eq!(parse_version("1.2.3-beta"), (1, 2, 3, 1, 0));
    assert_eq!(parse_version("2.0.0-rc1"), (2, 0, 0, 2, 1));
    assert_eq!(parse_version("2.0.0-alpha1"), (2, 0, 0, 0, 1));
}

#[test]
fn newer_with_prerelease() {
    assert!(newer("2.0.0-rc1", "2.0.0-beta2"));
    assert!(!newer("2.0.0-beta2", "2.0.0-rc1"));
    assert!(newer("2.0.0", "1.9.9-rc1"));
    assert!(!newer("1.9.9-rc1", "2.0.0"));
}

#[test]
fn asset_selection_exact() {
    let mut assets = HashMap::new();
    assets.insert("FreeDictateSetup.exe".to_string(), "https://example.com/setup.exe".to_string());
    assets.insert("FreeDictatePortable.zip".to_string(), "https://example.com/port.zip".to_string());
    let rel = Release {
        version: "3.6.1".to_string(),
        tag: "v3.6.1".to_string(),
        name: "Release".to_string(),
        notes: "".to_string(),
        url: "".to_string(),
        prerelease: false,
        assets,
    };
    let (name, url) = _asset(&rel, false).unwrap();
    assert!(name.contains("Setup"));
    let (name2, _) = _asset(&rel, true).unwrap();
    assert!(name2.contains("Portable"));
}

#[test]
fn portable_false_prefers_exe() {
    let mut assets = HashMap::new();
    assets.insert("FreeDictateSetup.exe".to_string(), "https://example.com/setup.exe".to_string());
    assets.insert("FreeDictate.zip".to_string(), "https://example.com/zip.zip".to_string());
    let rel = Release {
        version: "3.6.1".to_string(),
        tag: "v3.6.1".to_string(),
        name: "Release".to_string(),
        notes: "".to_string(),
        url: "".to_string(),
        prerelease: false,
        assets,
    };
    let (name, _) = _asset(&rel, false).unwrap();
    assert!(name.ends_with(".exe"));
}

#[test]
fn portable_true_prefers_zip() {
    let mut assets = HashMap::new();
    assets.insert("FreeDictateSetup.exe".to_string(), "https://example.com/setup.exe".to_string());
    assets.insert("FreeDictatePortable.zip".to_string(), "https://example.com/port.zip".to_string());
    let rel = Release {
        version: "3.6.1".to_string(),
        tag: "v3.6.1".to_string(),
        name: "Release".to_string(),
        notes: "".to_string(),
        url: "".to_string(),
        prerelease: false,
        assets,
    };
    let (name, _) = _asset(&rel, true).unwrap();
    assert!(name.ends_with(".zip"));
}

#[test]
fn no_matching_asset_error() {
    let mut assets = HashMap::new();
    assets.insert("other.txt".to_string(), "https://example.com/other.txt".to_string());
    let rel = Release {
        version: "3.6.1".to_string(),
        tag: "v3.6.1".to_string(),
        name: "Release".to_string(),
        notes: "".to_string(),
        url: "".to_string(),
        prerelease: false,
        assets,
    };
    assert!(_asset(&rel, false).is_err());
    assert!(_asset(&rel, true).is_err());
}

#[test]
fn missing_sha_expected() {
    let mut assets = HashMap::new();
    assets.insert("test.zip".to_string(), "https://example.com/test.zip".to_string());
    let rel = Release {
        version: "3.6.1".to_string(),
        tag: "v3.6.1".to_string(),
        name: "Release".to_string(),
        notes: "".to_string(),
        url: "".to_string(),
        prerelease: false,
        assets,
    };
    let sha = _expected_sha(&rel, "test.zip");
    assert!(sha.is_none());
}

#[test]
fn parse_version_handles_extra() {
    let v = parse_version("4.0.0-beta.1");
    assert_eq!(v, (4, 0, 0, 1, 1));
}

#[test]
fn newer_identical_is_false() {
    assert!(!newer("3.6.1", "3.6.1"));
}

#[test]
fn asset_name_case_insensitive() {
    let mut assets = HashMap::new();
    assets.insert("FreeDictatePortable.zip".to_string(), "https://example.com/port.zip".to_string());
    let rel = Release {
        version: "3.6.1".to_string(),
        tag: "v3.6.1".to_string(),
        name: "Release".to_string(),
        notes: "".to_string(),
        url: "".to_string(),
        prerelease: false,
        assets,
    };
    let (name, _) = _asset(&rel, true).unwrap();
    assert_eq!(name, "FreeDictatePortable.zip");
}

#[test]
fn asset_prefers_portable_even_if_not_exact() {
    let mut assets = HashMap::new();
    assets.insert("FreeDictate.zip".to_string(), "https://example.com/zip.zip".to_string());
    assets.insert("FreeDictatePortable.zip".to_string(), "https://example.com/port.zip".to_string());
    let rel = Release {
        version: "3.6.1".to_string(),
        tag: "v3.6.1".to_string(),
        name: "Release".to_string(),
        notes: "".to_string(),
        url: "".to_string(),
        prerelease: false,
        assets,
    };
    let (name, _) = _asset(&rel, true).unwrap();
    assert!(name.ends_with("Portable.zip"));
}

#[test]
fn asset_prefers_setup_exe_over_other_exe() {
    let mut assets = HashMap::new();
    assets.insert("FreeDictateSetup.exe".to_string(), "https://example.com/setup.exe".to_string());
    assets.insert("FreeDictate.exe".to_string(), "https://example.com/simple.exe".to_string());
    let rel = Release {
        version: "3.6.1".to_string(),
        tag: "v3.6.1".to_string(),
        name: "Release".to_string(),
        notes: "".to_string(),
        url: "".to_string(),
        prerelease: false,
        assets,
    };
    let (name, _) = _asset(&rel, false).unwrap();
    assert!(name.ends_with("Setup.exe"));
}

#[test]
fn parse_version_with_underscore() {
    let v = parse_version("1_2_3");
    assert_eq!(v, (1, 0, 0, 3, 0));
}

#[test]
fn newer_differentiates_prerelease() {
    assert!(newer("3.6.0", "3.5.9-beta"));
    assert!(!newer("3.5.9-beta", "3.6.0"));
}

#[test]
#[ignore = "fetches SHA256SUMS from the fake release URL over the network; the offline no-checksum path is covered by missing_sha_expected"]
fn _expected_sha_finds_in_SHA256SUMS() {
    let mut assets = HashMap::new();
    assets.insert("SHA256SUMS".to_string(), "https://example.com/sha256sums".to_string());
    assets.insert("FreeDictate.exe".to_string(), "https://example.com/download".to_string());
    let rel = Release {
        version: "3.6.1".to_string(),
        tag: "v3.6.1".to_string(),
        name: "Release".to_string(),
        notes: "".to_string(),
        url: "".to_string(),
        prerelease: false,
        assets,
    };
    let sha = _expected_sha(&rel, "FreeDictate.exe");
    assert!(sha.is_some());
}

#[test]
fn _asset_should_match_zip_with_portable_in_name() {
    let mut assets = HashMap::new();
    assets.insert("FreeDictate.zip".to_string(), "https://example.com/zip.zip".to_string());
    assets.insert("FreeDictatePortable.zip".to_string(), "https://example.com/port.zip".to_string());
    let rel = Release {
        version: "3.6.1".to_string(),
        tag: "v3.6.1".to_string(),
        name: "Release".to_string(),
        notes: "".to_string(),
        url: "".to_string(),
        prerelease: false,
        assets,
    };
    let (name, _) = _asset(&rel, true).unwrap();
    assert!(name.ends_with("Portable.zip"));
}