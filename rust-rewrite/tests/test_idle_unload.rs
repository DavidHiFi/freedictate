//! Idle VRAM release parity — offline-testable parts from test_idle_unload.py.
//! No real audio or model files: uses crate public API only. Engine paths that
//! need a loaded model / active threads are #[ignore] with a reason.

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
    (
        Engine::new(
            Config::new(std::env::temp_dir().join("freedictate-test-idle")),
            emit,
        ),
        events,
    )
}

// ---- Config-level parity (port of test_idle_unload_defaults_and_coercion) ----

/// idle_unload defaults to on, like Python's Config defaults.
#[test]
fn idle_unload_default_is_true() {
    let cfg = Config::new(std::env::temp_dir().join("test-idle-defaults.json"));
    assert_eq!(cfg.bool_value("idle_unload"), true);
}

/// idle_seconds defaults to 0 (unload right after each take).
#[test]
fn idle_seconds_default_is_zero() {
    let cfg = Config::new(std::env::temp_dir().join("test-idle-zero.json"));
    assert_eq!(cfg.number_value("idle_seconds"), 0);
}

/// A large idle_seconds is clamped to the 3600s ceiling (cf. Python 5000 -> 3600).
#[test]
fn idle_seconds_clamped_to_ceiling() {
    let mut cfg = Config::new(std::env::temp_dir().join("test-idle-clamp.json"));
    cfg.update(&serde_json::json!({ "idle_seconds": 5000 }));
    assert_eq!(cfg.number_value("idle_seconds"), 3600);
}

/// A negative idle_seconds is clamped to 0.
#[test]
fn idle_seconds_negative_clamped_to_zero() {
    let mut cfg = Config::new(std::env::temp_dir().join("test-idle-neg.json"));
    cfg.update(&serde_json::json!({ "idle_seconds": -3 }));
    assert_eq!(cfg.number_value("idle_seconds"), 0);
}

// ---- Engine-offline parity ----

/// toggle_pause reaches the unload path without threads and reports the state
/// event — the offline-exercisable slice of test_pause_unloads_and_resume_reloads.
#[test]
fn pause_toggles_and_emits_state() {
    let (mut engine, events) = test_engine();
    assert!(engine.toggle_pause());
    assert!(!engine.toggle_pause());
    let state_events = events
        .lock()
        .unwrap()
        .iter()
        .filter(|(e, _)| e == "state")
        .count();
    assert_eq!(state_events, 2, "each toggle emits one state event");
}

// ---- Gaps requiring a loaded Voice / running threads (not offline-testable) ----

/// unload_model_now only frees when voice.is_some(); reaching that needs a real
/// downloaded model, which needs the loader thread + network.
#[test]
#[ignore = "unload_model_now needs a loaded Voice (model download) to actually free; not offline-testable"]
fn unload_frees_model_and_emits() {}

/// Busy-state guards (listening/transcribing/downloading/loading, queued takes)
/// only occur during a real recording or decode.
#[test]
#[ignore = "busy-state guards need an active take/recording, which needs the poller thread"]
fn unload_refuses_while_busy() {}

#[test]
#[ignore = "decode-lock path needs a live Voice decode holding shared.voice"]
fn unload_waits_out_a_file_decode() {}

/// "Unloaded to save VRAM" only renders once state leaves loading (needs start())
/// with a loaded voice, so it is not reachable in an offline test.
#[test]
#[ignore = "status_text VRAM line needs state=='ready' after start(), unreachable offline"]
fn usable_when_unloaded_and_status_text_mentions_vram() {}

/// resume-preload logic calls load_model_async_on which spawns a real loader thread.
#[test]
#[ignore = "resume reload spawns the loader thread (model download); not offline-testable"]
fn pause_unloads_and_resume_reloads() {}

/// wait_for_model polls a real reloading Voice; no model is loaded offline.
#[test]
#[ignore = "wait_for_model waits on a loaded Voice that only exists after a download"]
fn wait_for_model_returns_quickly_when_ready() {}

/// writer.set_idle_seconds / IDLE_STOP_S live in writer.rs and touch the
/// (textproc-only) writing thread, not the engine public API.
#[test]
#[ignore = "writer.idle_seconds wiring is not exposed via Engine public API in this build"]
fn writer_idle_timeout_follows_setting() {}

/// release_after_take is a private fn driven by finish_job during a real take.
#[test]
#[ignore = "release_after_take is private and fires during a real transcription take"]
fn release_after_take_drops_everything() {}

#[test]
#[ignore = "release_after_take is private and fires during a real transcription take"]
fn release_after_take_waits_for_queued_or_recording() {}

#[test]
#[ignore = "release_after_take is private and fires during a real transcription take"]
fn release_after_take_kept_when_timeout_positive() {}

/// The idle_loop watcher itself is a spawning thread; its schedule is verified
/// only by running start() + real time, not by unit test.
#[test]
#[ignore = "idle_loop runs on a background thread started by Engine::start"]
fn idle_loop_unloads_after_timeout() {}
