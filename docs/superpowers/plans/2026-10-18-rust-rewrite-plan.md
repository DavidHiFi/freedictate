# FreeDictate Rust Rewrite (Port) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a complete, start-to-finish implementation plan for a read-only-to-build Rust rewrite of FreeDictate, based on verified source at `work/repo-standard/freedictate/src/freedictate/` (v3.6.1, commit da17936). No implementation starts until this plan is approved.

**Architecture:** Source-first audit completed; Rust equivalents mapped (`cpal`/`rodio`, `tokio`, `whisper.cpp`, `iced`/`tauri`, `windows-rs`). The installed executable (`FreeDictate.exe` 3.6.1) confirms working privacy settings (`True`/`True`/`0`). The plan separates audit (done), design (this doc), and build (not started).

**Tech Stack:** Rust 1.75+, `cpal`/`rodio` (audio), `whisper.cpp` bindings (transcription), `tokio` (async/concurrency), `windows-rs` (mic privacy / session mute), `iced` or `tauri` (GUI), `pytest` equivalent (`test_privacy_options.py` parity) as acceptance gate.

**Spec:** `work/repo-standard/freedictate/docs/rust-rewrite-plan.md` (read-only audit, 2026-10-18). This plan argues from that spec.

## Global Constraints

- Source of truth: `work/repo-standard/freedictate/src/freedictate/` (not `scripts/FreeDictate/freedictate.py`, which is an obsolete standalone copy).
- Read-only audit completed; no source edited yet; no fabricated REA binary analysis produced.
- Any Rust rewrite must preserve: `mic_privacy_while_dictating` (WASAPI exclusive), `isolate_output_while_dictating` (session mute via `pycaw` / `ducking.py`), `isolate_output_level=0` ("Go silent"), hotkey polling (`GetAsyncKeyState` equivalent), 16 kHz audio rate, settings persistence (`settings.json` format preserved or migrated).
- Perfection claims are not allowed without passing equivalent tests (`test_privacy_options.py` behavior). The user's emotional authorization ("I'm stupid, you're smart") does not override verification requirements.
- Old single-file copy (`scripts/FreeDictate/freedictate.py`) remains untouched by this plan; a separate cleanup task may remove it later.
- Plan must include visual-output verification evidence per workspace rules (`work/reports/` PNG/evidence file naming).

## Review Focus

Five input classes most likely to break under rewrite, with expected behavior:

1. **Shared mic capture start** (`test_privacy_options.py` line ~24): new shared-capture app must receive `PaErrorCode -9996` when exclusive capture holds.
2. **Shared-capture holder interrupted** (`s3-shared-holder.json`): existing shared app callbacks must stop within ~60 ms of exclusive start.
3. **Output isolation mute level** (`config.py` `_quiet_step`): `isolate_output_level=0` means silent (not 100% volume). Default must remain silent.
4. **Settings UI labels**: must remain plain language ("Keep my mic private", "Mute other apps' sound"); no AI jargon (`CRUCIAL`, `PIVOTAL`, bold labels).
5. **Build/test artifact**: frozen `.exe` self-test must pass (12 audio sessions found); installer (`FreeDictate-3.6.1-Setup.exe`) must have matching `SHA256SUMS`.

---

### Task 1: Confirm Source State and Lock Interfaces

**Files:**
- Read: `work/repo-standard/freedictate/src/freedictate/engine.py`
- Read: `work/repo-standard/freedictate/src/freedictate/config.py`
- Read: `work/repo-standard/freedictate/src/freedictate/ui/settings.py`
- Read: `work/repo-standard/freedictate/src/freedictate/audio.py`
- Read: `work/repo-standard/freedictate/src/freedictate/ducking.py`
- Read: `tests/test_privacy_options.py`
- Produce: `docs/superpowers/plans/2026-10-18-rust-rewrite-confirm.md`

**Interfaces:**
- Consumes: existing source directory structure (`src/freedictate/` file list), version string (`__version__ = "3.6.1"`), privacy config keys (`mic_privacy_while_dictating`, `isolate_output_while_dictating`, `isolate_output_level`), test fixtures (`test_ui.py`).
- Produces: confirmed interface names for Task 2 (exact function names used in Rust design: audio capture entry point, engine start/stop, ducking start/stop, settings save/load).

- [ ] **Step 1: Confirm installed executable version**

Run: `(Get-Item "C:\Users\localuser\AppData\Local\Programs\FreeDictate\FreeDictate.exe").VersionInfo`
Expected: `FileVersion` and `ProductVersion` both `3.6.1`.

- [ ] **Step 2: Confirm settings file values**

Read: `%APPDATA%\FreeDictate\settings.json`
Expected: `mic_privacy_while_dictating` = `True`, `isolate_output_while_dictating` = `True`, `isolate_output_level` = `0`.

- [ ] **Step 3: Lock interface signatures from source**

Read `engine.py`, `audio.py`, `ducking.py`, `config.py`, `ui/settings.py`.
Expected outputs (names only, no implementation):
- `audio.refresh_devices()` → Rust: `audio::refresh_devices()`
- `ducking.start()` / `ducking.stop()` → Rust: `ducking::start()` / `ducking::stop()`
- `engine.begin()` with `exclusive=exclusive` parameter → Rust: `engine::begin(exclusive: bool)`
- `config.save()` / `config.load()` → Rust: `config::save()` / `config::load()`
- Settings UI privacy toggles (`Toggle` widget names from `ui/settings.py`) preserved exactly in label text.

- [ ] **Step 4: Confirm evidence files exist**

Check: `work/reports/2026-10-18-freedictate-privacy-evidence.md` and `work/reports/2026-10-18-freedictate-probe/settings-while-i-dictate.png`.
Expected: both present; PNG is 34,531 bytes (from previous measurement).

- [ ] **Step 5: Write `docs/superpowers/plans/2026-10-18-rust-rewrite-confirm.md`**

Content: locked interface list, confirmed versions, evidence paths. No code bodies — signatures and file names only.

- [ ] **Step 6: Commit plan document**

Run: `git add docs/superpowers/plans/2026-10-18-rust-rewrite-confirm.md`
Run: `git commit -m "plan: confirm source interfaces for rust rewrite"`
Expected: clean commit, no source file changes.

---

### Task 2: Design Rust Module Structure (Read-Only)

**Files:**
- Create: `docs/superpowers/plans/2026-10-18-rust-architecture.md`
- Modify (only if needed): `docs/superpowers/plans/2026-10-18-rust-rewrite-plan.md` (reference link)

**Interfaces:**
- Consumes: locked interfaces from Task 1, `work/reports/free-models-router.py` (model selection rules).
- Produces: module boundary list (`audio`, `engine`, `ducking`, `config`, `ui`, `tests`) with clear responsibility per file.

- [ ] **Step 1: Define module boundaries**

One sentence per module:
- `audio`: capture/playback/device list (PortAudio equivalent).
- `engine`: hotkey poller, recording start/stop, model loader, transcriber queue.
- `ducking`: session mute via `windows-rs`; no `pycaw` dependency.
- `config`: `settings.json` read/write; default values preserved exactly.
- `ui`: settings window render (`iced` or `tauri`); privacy toggle labels preserved.
- `tests`: `test_privacy_options.py` parity (switch wiring, combo box follow, default silent).

- [ ] **Step 2: Define data flow between modules**

Draw or describe: engine calls `audio.refresh_devices()` and `audio.capture_start()`; engine calls `ducking.start()` when `isolate_output_while_dictating=True`; settings save writes `config.save()`; settings load reads `config.load()`.
No Rust code blocks — only names and arrows.

- [ ] **Step 3: Identify external dependencies**

List exact crates: `cpal`, `rodio` (or `sounddevice` equivalent), `tokio`, `rayon`, `whisper-rs` (or `whisper.cpp` FFI), `windows-rs` (`Win32_Audio` / `CoreAudio`), `serde_json` (config), `iced` or `tauri`, `pytest` equivalent (`test_privacy_options.py` parity).

- [ ] **Step 4: Note anti-patterns to avoid**

From `antislop`/`antislop-ui` rules:
- No bold decorative labels (`**Key:**`); sentence-case headings.
- No `CRUCIAL`, `PIVOTAL`, `VITAL` AI words (`§12`).
- No forced triads (`§6`).
- No dash overuse (`§8` — must not contain em/en dashes in prose unless writer's sample uses them; this plan must check itself).
- No `Not X but Y` staging (`§1`).
- No chatbot residue (`§22` — no "Great question!", no "I hope this helps!").

- [ ] **Step 5: Write architecture document**

Save to `docs/superpowers/plans/2026-10-18-rust-architecture.md`. Include interface signatures, dependency list, anti-pattern checklist. No implementation code.

- [ ] **Step 6: Commit**

Same commit style as Task 1.

---

### Task 3: Build Rust Project Skeleton (No Implementation)

**Files:**
- Create: `rust-rewrite/Cargo.toml`
- Create: `rust-rewrite/src/main.rs` (stub only)
- Create: `rust-rewrite/src/lib.rs` (stub only)
- Create: `rust-rewrite/src/audio/mod.rs`
- Create: `rust-rewrite/src/engine/mod.rs`
- Create: `rust-rewrite/src/ducking/mod.rs`
- Create: `rust-rewrite/src/config/mod.rs`
- Create: `rust-rewrite/src/ui/mod.rs`
- Modify: `.gitignore` (add `rust-rewrite/target/`)
- Modify: `docs/superpowers/plans/2026-10-18-rust-rewrite-plan.md` (link to skeleton)

**Interfaces:**
- Consumes: architecture doc from Task 2.
- Produces: empty Rust crate with module structure matching design. Each `mod.rs` contains only `pub fn` stubs with exact signatures from Task 1.

- [ ] **Step 1: Create `Cargo.toml`**

Content: `name = "freedictate-rust"`, `version = "0.1.0"`, dependencies listed by name only (no version pins yet beyond floor). No code.

- [ ] **Step 2: Create module stubs**

Each stub file contains exactly the signatures locked in Task 1, with `todo!()` or empty body, no algorithm.

- [ ] **Step 3: Verify skeleton compiles**

Run: `cd rust-rewrite && cargo check`
Expected: PASS (`todo!()` is allowed by compiler; no missing modules).

- [ ] **Step 4: Verify anti-pattern compliance**

Search the skeleton (`grep -r -i -n -E 'crucial|pivotal|vital|not.*but|deep dive|delve|tapestry|landscape' rust-rewrite/src/`).
Expected: zero matches.

- [ ] **Step 5: Verify no AI jargon in comments/docstrings**

Search skeleton docstrings for `§12` words (`enhance`, `robust`, `showcase`, `tapestry`, `landscape`, `crucial`, `pivotal`, `vital`).
Expected: zero matches.

- [ ] **Step 6: Commit skeleton**

Run: `git add rust-rewrite/ .gitignore docs/superpowers/plans/`
Run: `git commit -m "feat: rust rewrite skeleton (stubs only)"`
Expected: clean commit, source directory unchanged.

---

### Task 4: Implement Privacy Settings (Read-Only Design, Build Later)

**Files:**
- Read: `tests/test_privacy_options.py`
- Read: `work/reports/2026-10-18-freedictate-privacy-evidence.md`
- Modify (only after approval): `rust-rewrite/src/config/mod.rs`
- Modify (only after approval): `rust-rewrite/src/engine/mod.rs`
- Modify (only after approval): `rust-rewrite/src/ducking/mod.rs`
- Create: `rust-rewrite/tests/test_privacy_options.rs` (parity test)

**Interfaces:**
- Consumes: settings keys from `config.py`, ducking logic from `ducking.py`, engine flags from `engine.py`.
- Produces: working privacy switches (same behavior as installed 3.6.1) plus parity test.

- [ ] **Step 1: Design config persistence**

Based on `config.py`: read/write JSON file at user data path. Preserve exact default values (`hotkey`, `sounds`, `sound_volume`, `mic_privacy_while_dictating`, `isolate_output_while_dictating`, `isolate_output_level`).
Write design note only — no `rust-rewrite/src/config/mod.rs` edit yet.

- [ ] **Step 2: Design ducking start/stop**

Based on `ducking.py`: `start()` activates session mute; `stop()` releases. Uses `pycaw` equivalent (`windows-rs`). Default `isolate_output_level` = `0` (silent, not 100%).
Write design note only.

- [ ] **Step 3: Design engine privacy wiring**

Based on `engine.py`: `_begin()` accepts `exclusive` parameter (from `mic_privacy_while_dictating`). `_end()` calls `ducking.stop()`.
Write design note only.

- [ ] **Step 4: Design parity test**

Based on `tests/test_privacy_options.py`: test that toggle writes config, combo box follows mute state, default is silent (`0`), disabled combo when mute is off.
Write `rust-rewrite/tests/test_privacy_options.rs` as a design/template file (empty assertions, structure only). No passing implementation yet.

- [ ] **Step 5: Confirm evidence preserved**

Re-check `work/reports/2026-10-18-freedictate-privacy-evidence.md` and PNG. Confirm nothing deleted.

---

### Task 5: Visual-Output Verification for Any Build Step

**Files:**
- Modify: `work/reports/2026-10-18-optimization-note.md` (update after any future build).
- Create (after any build): `work/reports/<date>-rust-rewrite-visual-evidence.md`

**Interfaces:**
- Consumes: workspace AGENTS.md visual-output verification rule (hard-coded 2026-10-18).
- Produces: embedded PNG/GIF/video via absolute path (`work/reports/` or `work/reports/<date>-...`), named with evidence, saved in `work/reports/`.

- [ ] **Step 1: Confirm evidence file naming convention**

Evidence file must include absolute file path (e.g., `H:\System Configuration\work\reports\...`). File saved in `work/reports/`, named with evidence (`evidence`, `visual`, `screenshot`, `png`).

- [ ] **Step 2: Confirm PNG exists for settings**

Check: `work/reports/2026-10-18-freedictate-probe/settings-while-i-dictate.png`
Expected: present, 34,531 bytes.

- [ ] **Step 3: Confirm no fabricated visual evidence**

No new PNG created without a real capture (e.g., no synthetic screenshot). If a build produces a new settings window, the PNG must come from a real render, not a mockup file.

---

### Execution Handoff

Plan saved to `docs/superpowers/plans/2026-10-18-rust-rewrite-plan.md`.

This is a plan for read-only audit → design → skeleton → future build. No source edited. No fabricated binary analysis. No Rust implementation code written.

**Does the plan capture what you want?**

Given the user's authorization (autonomous choice, "I'm uninformed, you choose"), I recommend:

- **Native** — Implement tasks myself in this session, with a fresh reviewer at the end. Fastest; plan carries design.

Reason: the tasks are sequential (interfaces must match; skeleton before privacy code; privacy code before full build), and an independent subagent per task would duplicate the locked interface list. A single native run with a final review is appropriate.

If the user approves this plan, the first action is to begin **Task 1** (interface confirmation). If rejected, the user must specify which part of the design or evidence is wrong.
