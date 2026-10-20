//! ggml whisper.cpp models for the Rust engine: catalog, download with
//! progress and cancel, and thin transcription wrapper. Speech side of
//! models.py; the desired-builder variants there (faster-whisper, Parakeet)
//! do not exist in this build.

use std::io::{Read, Write};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};

use whisper_rs::{FullParams, SamplingStrategy, WhisperContext, WhisperContextParameters};

pub struct ModelInfo {
    pub name: &'static str,
    pub title: &'static str,
    pub size_mb: u64,
    pub english_only: bool,
}

/// ggml models from the whisper.cpp Hugging Face repo. Sizes in MB are the
/// file sizes users see before download; only these are wired up.
/// The silero VAD model rides the same repo and naming (ggml-<name>.bin).
pub const VAD_MODEL_NAME: &str = "silero-v5.1.2";

pub const CATALOG: &[ModelInfo] = &[
    ModelInfo {
        name: "tiny.en",
        title: "Tiny",
        size_mb: 77,
        english_only: true,
    },
    ModelInfo {
        name: "base.en",
        title: "Base",
        size_mb: 148,
        english_only: true,
    },
    ModelInfo {
        name: "small.en",
        title: "Small",
        size_mb: 487,
        english_only: true,
    },
    ModelInfo {
        name: "medium.en",
        title: "Medium",
        size_mb: 1530,
        english_only: true,
    },
    ModelInfo {
        name: "large-v3-turbo",
        title: "Large v3 Turbo",
        size_mb: 1620,
        english_only: false,
    },
    ModelInfo {
        name: "large-v3",
        title: "Large v3",
        size_mb: 3090,
        english_only: false,
    },
    ModelInfo {
        name: "tiny",
        title: "Tiny (multilingual)",
        size_mb: 77,
        english_only: false,
    },
    ModelInfo {
        name: "base",
        title: "Base (multilingual)",
        size_mb: 148,
        english_only: false,
    },
    ModelInfo {
        name: "small",
        title: "Small (multilingual)",
        size_mb: 487,
        english_only: false,
    },
    ModelInfo {
        name: "medium",
        title: "Medium (multilingual)",
        size_mb: 1530,
        english_only: false,
    },
];

/// Which downloaded model to dictate with while the chosen one downloads.
pub const FALLBACK_ORDER: [&'static str; 3] = ["small.en", "base.en", "tiny.en"];

fn by_name(name: &str) -> Option<&'static ModelInfo> {
    CATALOG.iter().find(|m| m.name == name)
}

pub fn models_dir() -> PathBuf {
    std::env::var_os("APPDATA")
        .map(|appdata| {
            PathBuf::from(appdata)
                .join("FreeDictate-Rust")
                .join("models")
        })
        .unwrap_or_else(|| PathBuf::from("models"))
}

/// File of a downloaded model, or None when it is not on disk.
pub fn local_path(name: &str) -> Option<PathBuf> {
    // Only catalog names reach the file system; nothing else is ever written.
    if by_name(name).is_none() {
        return None;
    }
    let path = models_dir().join(format!("ggml-{name}.bin"));
    path.is_file().then_some(path)
}

pub fn is_downloaded(name: &str) -> bool {
    local_path(name).is_some()
}

/// Streamed download to a .part file with progress and cancel, renamed into
/// place when complete. URLs follow the Hugging Face CDN redirects.
pub fn download(
    name: &str,
    progress: &dyn Fn(u64, u64),
    cancel: &AtomicBool,
) -> Result<PathBuf, String> {
    let dir = models_dir();
    let final_path = dir.join(format!("ggml-{name}.bin"));
    if final_path.is_file() {
        return Ok(final_path);
    }
    std::fs::create_dir_all(&dir).map_err(|e| format!("model folder: {e}"))?;
    let part_path = dir.join(format!("ggml-{name}.bin.part"));
    let url = format!("https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{name}.bin");
    let mut response = ureq::get(&url)
        .call()
        .map_err(|e| format!("Download request failed: {e}"))?;
    if !response.status().is_success() {
        return Err(format!("Download failed with HTTP {}", response.status()));
    }
    let total = response.body().content_length().unwrap_or(0);
    let mut reader = response.body_mut().as_reader();
    let mut file = std::fs::File::create(&part_path).map_err(|e| format!("Download file: {e}"))?;
    let mut buffer = vec![0u8; 1 << 20];
    let mut done: u64 = 0;
    loop {
        if cancel.load(Ordering::Relaxed) {
            drop(file);
            let _ = std::fs::remove_file(&part_path);
            return Err("Download cancelled".to_string());
        }
        let n = reader
            .read(&mut buffer)
            .map_err(|e| format!("Download read: {e}"))?;
        if n == 0 {
            break;
        }
        file.write_all(&buffer[..n])
            .map_err(|e| format!("Download write: {e}"))?;
        done += n as u64;
        progress(done, total);
    }
    drop(file);
    // Arriving short of the advertised size is a broken download; a .part
    // file must never be renamed into place as if it were whole.
    if total > 0 && done < total {
        let _ = std::fs::remove_file(&part_path);
        return Err("Download ended early. Try again.".to_string());
    }
    progress(done.max(total), total.max(done));
    std::fs::rename(&part_path, &final_path)
        .map_err(|e| format!("Moving the downloaded model into place failed: {e}"))?;
    Ok(final_path)
}

/// One loaded whisper context. Thin wrapper over whisper-rs; not Clone.
pub struct Voice {
    ctx: WhisperContext,
}

impl Voice {
    pub fn load(path: &std::path::Path) -> Result<Voice, String> {
        let ctx = WhisperContext::new_with_params(path, WhisperContextParameters::default())
            .map_err(|e| format!("Loading the model failed: {e}"))?;
        Ok(Voice { ctx })
    }

    pub fn transcribe(&self, samples: &[f32], language: Option<&str>) -> Result<String, String> {
        self.transcribe_with(samples, language, false, None)
    }

    /// Transcribe with whisper.cpp's VAD filter and initial prompt. `vad`
    /// needs the silero model in the models folder (the settings row
    /// downloads it on first use); without the file the take transcribes
    /// unfiltered, exactly like the Python engine's vad_filter=False path.
    pub fn transcribe_with(
        &self,
        samples: &[f32],
        language: Option<&str>,
        vad: bool,
        vocabulary: Option<&str>,
    ) -> Result<String, String> {
        let mut state = self
            .ctx
            .create_state()
            .map_err(|e| format!("Starting the decoder failed: {e}"))?;
        let mut params = FullParams::new(SamplingStrategy::Greedy { best_of: 1 });
        // None means auto-detect, like language=None in the Python engine.
        params.set_language(language);
        params.set_translate(false);
        params.set_single_segment(false);
        if let Some(prompt) = vocabulary {
            params.set_initial_prompt(prompt);
        }
        if vad {
            // enable_vad panics without a model path set first; only the
            // existing silero file enables the filter.
        let path = models_dir().join(format!("ggml-{}.bin", VAD_MODEL_NAME));
            if path.is_file() {
                params.set_vad_model_path(Some(path.to_string_lossy().as_ref()));
                params.enable_vad(true);
            }
        }
        state
            .full(params, samples)
            .map_err(|e| format!("Transcription failed: {e}"))?;
        let mut out = String::new();
        for i in 0..state.full_n_segments() {
            if let Some(seg) = state.get_segment(i) {
                if let Ok(text) = seg.to_str_lossy() {
                    out.push_str(&text);
                }
            }
        }
        Ok(out)
    }

    /// Drop the context; its memory goes back to the system.
    pub fn unload(self) {}
}
