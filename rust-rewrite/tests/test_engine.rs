// Pure engine-logic tests: no microphone, no model download, no threads.
// Engine::start is never called here, so nothing spawns; Config::new parses
// defaults only and never touches the disk.

use std::sync::{Arc, Mutex};

use freedictate_rust::config::Config;
use freedictate_rust::engine::{Engine, EmitFn};

type EventLog = Arc<Mutex<Vec<(String, serde_json::Value)>>>;

fn test_engine() -> (Engine, EventLog) {
    let events: EventLog = Arc::new(Mutex::new(Vec::new()));
    let sink = Arc::clone(&events);
    let emit: EmitFn = Arc::new(move |event: &str, payload: serde_json::Value| {
        sink.lock().unwrap().push((event.to_string(), payload));
    });
    let cfg = Config::new(
        std::env::temp_dir()
            .join("freedictate-test-engine")
            .join("settings-unused.json"),
    );
    (Engine::new(cfg, emit), events)
}

#[test]
fn starts_loading_with_the_readying_status_text() {
    let (engine, _) = test_engine();
    assert_eq!(engine.state(), "loading");
    assert_eq!(engine.status_text(), "Getting the speech model ready");
}

#[test]
fn model_status_starts_idle_without_progress() {
    let (engine, _) = test_engine();
    let (status, active, done, total) = engine.model_status();
    assert_eq!(status, "idle");
    assert_eq!(active, "");
    assert_eq!((done, total), (0, 0));
}

#[test]
fn pause_toggles_and_shows_in_status_text() {
    let (mut engine, events) = test_engine();

    assert!(engine.toggle_pause());
    assert_eq!(engine.status_text(), "Paused");
    assert!(!engine.toggle_pause());
    assert_eq!(engine.status_text(), "Getting the speech model ready");

    // Each toggle reports through the state event, engine.py style.
    let events = events.lock().unwrap();
    let state_events = events.iter().filter(|(e, _)| e == "state").count();
    assert_eq!(state_events, 2, "each toggle emits one state event");
}

#[test]
fn transcribe_file_stub_keeps_the_on_text_contract() {
    let (mut engine, events) = test_engine();

    let got: Arc<Mutex<String>> = Arc::new(Mutex::new(String::new()));
    let sink = Arc::clone(&got);
    engine.transcribe_file(
        "C:\\nonexistent\\take.wav",
        Box::new(move |text| {
            *sink.lock().unwrap() = text.to_string();
        }),
    );

    // The caller's banner clears either way: a callback always arrives.
    assert!(
        got.lock().unwrap().starts_with("error:"),
        "stub must call on_text, got {:?}",
        got.lock().unwrap()
    );
    assert!(
        events.lock().unwrap().iter().any(|(e, _)| e == "error"),
        "stub must report through the error event"
    );
}
