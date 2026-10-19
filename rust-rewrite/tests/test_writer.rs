use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use freedictate_rust::writer::{self, ChatResult, Server, WriterTestHooks};

/// The writer keeps its test hooks in one process-wide slot, so the tests that
/// use them run one after another.
static LOCK: Mutex<()> = Mutex::new(());

struct FakeServer {
    sent: Arc<Mutex<Vec<(String, String)>>>,
    answer: String,
}

impl Server for FakeServer {
    fn ensure(&self, name: &str, _wait: f64) -> bool {
        name == "standard"
    }
    fn chat(&self, system: &str, text: &str, _timeout: f64) -> ChatResult {
        self.sent
            .lock()
            .unwrap()
            .push((system.to_string(), text.to_string()));
        Ok(self.answer.clone())
    }
}

fn hooks(answer: &str) -> (WriterTestHooks, Arc<Mutex<Vec<(String, String)>>>) {
    let sent = Arc::new(Mutex::new(Vec::new()));
    let mut h = WriterTestHooks::default();
    h.ready = Some(Box::new(|_: &str| String::new()));
    h.server = Some(Arc::new(FakeServer {
        sent: sent.clone(),
        answer: answer.to_string(),
    }));
    (h, sent)
}

const TAKE: &str =
    "I want, I want you to update the readme and then and then push it to GitHub when the tests pass";

#[test]
fn rewrite_returns_clean_text_and_strips_wrappers() {
    let _guard = LOCK.lock().unwrap();
    let (h, _sent) = hooks(
        "Here is the cleaned text:\n\"I want you to update the readme and then push it to GitHub when the tests pass.\"",
    );
    writer::set_test_hooks(h);
    let out = writer::rewrite(TAKE, "standard", "", 30.0);
    writer::clear_test_hooks();
    assert_eq!(
        out.as_deref(),
        Some("I want you to update the readme and then push it to GitHub when the tests pass.")
    );
}

#[test]
fn rewrite_rejects_an_answer_instead_of_the_text() {
    let _guard = LOCK.lock().unwrap();
    let (h, _sent) = hooks("Sure, I can help with that.");
    writer::set_test_hooks(h);
    let out = writer::rewrite(TAKE, "standard", "", 30.0);
    writer::clear_test_hooks();
    assert_eq!(out, None);
}

#[test]
fn a_changed_number_is_rejected() {
    let _guard = LOCK.lock().unwrap();
    let take = "it was using like 10 percent of my CPU and then and then the other one was at 40";
    let (h, _sent) = hooks(
        "It was using about -10 percent of my CPU, and the other one was at 40.",
    );
    writer::set_test_hooks(h);
    let out = writer::rewrite(take, "standard", "", 30.0);
    writer::clear_test_hooks();
    assert_eq!(out, None);
}

#[test]
fn vocabulary_reaches_the_prompt() {
    let _guard = LOCK.lock().unwrap();
    let (h, sent) = hooks(TAKE);
    writer::set_test_hooks(h);
    writer::rewrite(TAKE, "standard", "TestCord, , MochaCord", 30.0);
    writer::clear_test_hooks();
    let guard = sent.lock().unwrap();
    assert!(guard[0]
        .0
        .ends_with("Spell these names exactly as written: TestCord, MochaCord."));
}

#[test]
fn dashes_bold_and_curly_quotes_are_normalised() {
    let _guard = LOCK.lock().unwrap();
    let (h, _sent) = hooks(
        "I want you to update the readme \u{2014} and then push it to GitHub when the tests pass. **Don\u{2019}t** wait.",
    );
    writer::set_test_hooks(h);
    let take = "I want you to update the readme and then push it to GitHub when the tests pass don't wait";
    let out = writer::rewrite(take, "standard", "", 30.0);
    writer::clear_test_hooks();
    assert_eq!(
        out.as_deref(),
        Some("I want you to update the readme, and then push it to GitHub when the tests pass. Don't wait.")
    );
}

#[test]
fn short_takes_and_unready_models_skip_the_model() {
    let _guard = LOCK.lock().unwrap();
    let (mut h, sent) = hooks("x");
    h.ready = Some(Box::new(|_: &str| "Not downloaded yet.".to_string()));
    writer::set_test_hooks(h);

    assert_eq!(writer::rewrite("yes please", "standard", "", 30.0), None);
    assert_eq!(writer::rewrite(TAKE, "standard", "", 30.0), None);
    writer::clear_test_hooks();
    assert!(sent.lock().unwrap().is_empty(), "the model must not be asked");
}

#[test]
fn without_a_graphics_card_the_tidy_up_stays_off() {
    let _guard = LOCK.lock().unwrap();
    let mut h = WriterTestHooks::default();
    h.engine_installed = Some(true);
    h.gpu = Some((String::new(), 0));
    writer::set_test_hooks(h);
    assert!(writer::ready("standard").contains("graphics card"));

    let mut h2 = WriterTestHooks::default();
    h2.engine_installed = Some(true);
    h2.gpu = Some(("NVIDIA GeForce RTX 4070".to_string(), 12010));
    h2.model_path = Some(None);
    writer::set_test_hooks(h2);
    assert_eq!(writer::ready("standard"), "Not downloaded yet.");
    writer::clear_test_hooks();
}

#[test]
fn writing_models_are_pinned() {
    for m in writer::CATALOG.iter() {
        assert_eq!(m.revision.len(), 40, "{} revision is pinned", m.name);
        assert!(m.file.ends_with(".gguf"), "{} file is a gguf", m.name);
        assert!(m.size_mb > 0, "{} has a size", m.name);
    }
    assert_eq!(writer::ENGINE_SHA256.len(), 64);
    assert!(writer::ENGINE_URL.contains(writer::ENGINE_TAG));
}

#[test]
fn an_unknown_model_name_is_refused() {
    let _guard = LOCK.lock().unwrap();
    let mut h = WriterTestHooks::default();
    h.ready = Some(Box::new(|_: &str| String::new()));
    writer::set_test_hooks(h);
    // The hook answers for every name, so check the catalog itself.
    assert!(!writer::CATALOG.iter().any(|m| m.name == "nonsense"));
    writer::clear_test_hooks();
}

#[test]
fn the_engine_folder_is_the_rust_one() {
    // The Python app keeps %APPDATA%\FreeDictate; the Rust build must never
    // write there.
    let path: PathBuf = writer::writer_dir();
    assert!(
        path.to_string_lossy().contains("FreeDictate-Rust"),
        "the writer folder must live under the Rust app data: {}",
        path.display()
    );
    assert!(!path.to_string_lossy().contains("FreeDictate\\"));
}

#[test]
#[ignore = "needs the llama.cpp engine and a graphics card"]
fn the_engine_can_be_downloaded() {
    writer::download_engine(None, None).expect("engine download");
    assert!(writer::engine_installed());
}
