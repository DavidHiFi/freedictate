// Port of tests/test_history.py
// Offline checks against a temp-dir database: no network, no app data.

use freedictate_rust::history::History;
use std::path::PathBuf;

fn temp_db(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("fd-history-test-{}-{}", name, std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).expect("temp dir must exist");
    dir.join("h.db")
}

fn now() -> f64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .expect("clock")
        .as_secs_f64()
}

#[test]
fn test_add_search_stats_prune() {
    let path = temp_db("main");
    let h = History::new(&path, true);

    h.record_at("Hello world.", 2.0, "small.en", "notepad.exe", "", now() - 40.0 * 86400.0);
    h.add("Second take with 100% effort_here.", 3.5, "", "", "");

    assert_eq!(h.count(""), 2);

    let found: Vec<String> = h.search("100%", 200, 0).iter().map(|e| e.text.clone()).collect();
    assert_eq!(found, vec!["Second take with 100% effort_here.".to_string()]);

    // Underscore is a literal here, not a wildcard.
    assert!(!h.search("effort_", 200, 0).is_empty());
    assert!(h.search("effortXhere", 200, 0).is_empty());

    let st = h.stats();
    assert_eq!(st.count, 2);
    assert_eq!(st.words, 7);
    assert_eq!(st.words_week, 5);

    assert_eq!(h.prune(30), 1);
    assert_eq!(h.count(""), 1);

    h.clear();
    assert_eq!(h.count(""), 0);

    let _ = std::fs::remove_dir_all(path.parent().unwrap());
}

#[test]
fn test_legacy_import_and_export() {
    let path = temp_db("legacy");
    let dir = path.parent().unwrap().to_path_buf();
    let log = dir.join("transcripts.log");
    std::fs::write(
        &log,
        "2026-10-01 09:00:00 [12.3s] First one.\nnoise line\n2026-10-02 10:30:00 [1.0s] Second.\n",
    )
    .expect("log must write");

    let h = History::new(&path, true);
    assert_eq!(h.import_legacy_log(&log), 2);

    let recent: Vec<String> = h.recent(5).iter().map(|e| e.text.clone()).collect();
    assert_eq!(
        recent,
        vec!["Second.".to_string(), "First one.".to_string()]
    );

    let out = dir.join("out.txt");
    assert_eq!(h.export_text(&out), 2);
    let text = std::fs::read_to_string(&out).expect("export must exist");
    let first = text.split('\n').next().unwrap();
    assert_eq!(first, "2026-10-01 09:00:00 [12.3s] First one.");

    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn test_recent_is_newest_first_and_limited() {
    let path = temp_db("recent");
    let h = History::new(&path, true);

    h.record_at("First.", 1.0, "", "", "", 1000.0);
    h.record_at("Second.", 1.0, "", "", "", 2000.0);
    h.record_at("Third.", 1.0, "", "", "", 3000.0);

    let all: Vec<String> = h.recent(10).iter().map(|e| e.text.clone()).collect();
    assert_eq!(
        all,
        vec!["Third.".to_string(), "Second.".to_string(), "First.".to_string()]
    );

    let two = h.recent(2);
    assert_eq!(two.len(), 2);
    assert_eq!(two[0].text, "Third.");

    let _ = std::fs::remove_dir_all(path.parent().unwrap());
}

#[test]
fn test_word_count_uses_the_textproc_rule() {
    let path = temp_db("words");
    let h = History::new(&path, true);
    h.add("Don't stop, it's 3 o'clock.", 1.0, "", "", "");
    let entry = &h.recent(1)[0];
    assert_eq!(entry.words, 5);

    let _ = std::fs::remove_dir_all(path.parent().unwrap());
}

#[test]
fn test_history_off_writes_nothing() {
    let path = temp_db("off");
    let h = History::new(&path, false);
    h.add("Should not be kept.", 1.0, "small.en", "notepad.exe", "");
    assert_eq!(h.count(""), 0);
    assert!(h.recent(5).is_empty());

    let _ = std::fs::remove_dir_all(path.parent().unwrap());
}

#[test]
fn test_delete_removes_one_entry() {
    let path = temp_db("delete");
    let h = History::new(&path, true);
    h.add("One.", 1.0, "", "", "");
    let id = h.recent(1)[0].id;
    h.delete(id);
    assert_eq!(h.count(""), 0);

    let _ = std::fs::remove_dir_all(path.parent().unwrap());
}

#[test]
fn test_raw_keeps_the_text_before_the_tidy_up() {
    let path = temp_db("raw");
    let h = History::new(&path, true);
    h.add("Tidied text.", 1.0, "small.en", "notepad.exe", "raw transcript");
    let entry = &h.recent(1)[0];
    assert_eq!(entry.text, "Tidied text.");
    assert_eq!(entry.raw, "raw transcript");
    assert_eq!(entry.model, "small.en");
    assert_eq!(entry.app, "notepad.exe");

    let _ = std::fs::remove_dir_all(path.parent().unwrap());
}

#[test]
fn test_reopening_keeps_the_entries() {
    let path = temp_db("reopen");
    {
        let h = History::new(&path, true);
        h.add("Kept.", 1.0, "", "", "");
    }
    let h = History::new(&path, true);
    assert_eq!(h.count(""), 1);
    assert_eq!(h.recent(1)[0].text, "Kept.");

    let _ = std::fs::remove_dir_all(path.parent().unwrap());
}

#[test]
fn test_search_escapes_wildcards() {
    let path = temp_db("wildcards");
    let h = History::new(&path, true);
    h.add("100% sure", 1.0, "", "", "");
    h.add("1000 sure", 1.0, "", "", "");

    // The percent sign is a literal, so only the first entry matches.
    let found: Vec<String> = h.search("100%", 200, 0).iter().map(|e| e.text.clone()).collect();
    assert_eq!(found, vec!["100% sure".to_string()]);
    assert_eq!(h.count("100%"), 1);
    assert_eq!(h.count(""), 2);

    let _ = std::fs::remove_dir_all(path.parent().unwrap());
}
