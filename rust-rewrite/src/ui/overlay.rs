// Port of overlay.py: overlay view layer for the Fluent Rust rewrite.
// Provides a frameless, always-on-top window that displays the dictation
// status bar at the bottom (or top) of the screen.
//
// The master app wires this as a second iced::window with transparent
// background.  Positioning is driven by `_place()` and `bar_kind(cfg)`.
// Engine events (state changes, level peaks) are forwarded through the
// shared emit channel; the overlay does not engine.run() or touch the
// recording engine directly.
//
// Config keys (from DEFAULTS):
//   overlay               - enable the overlay bar
//   overlay_position      - "bottom" or "top"
//   overlay_timer         - show auto-hide timer behaviour
//   overlay_backdrop      - "solid", "mica_alt", "mica", "acrylic", "blur"

// The view layer is unused until the second window is wired into run();
// the allow marks the API as live-on-integration, not as leftovers.
#![allow(dead_code)]

use iced::widget::{column, text};
use iced::Length;

use crate::ui::icons;
use crate::ui::theme::Palette;
use crate::ui::widgets;
use crate::ui::Message;

/// Placement rule for the overlay bar on screen.
///
/// Determines where the bar appears and how it aligns, based on the
/// configured `overlay_position`.  The returned `Rectangle` is in
/// screen-space coordinates; the master window should position its
/// frameless iced window accordingly.
#[derive(Debug, Clone)]
pub enum BarPlace {
    /// Bar sits at the bottom edge of the primary monitor.
    Bottom,
    /// Bar sits at the top edge of the primary monitor.
    Top,
}

impl BarPlace {
    /// Apply the configured position key from the app config.
    pub fn from_cfg(position: &str) -> Self {
        match position {
            "top" => BarPlace::Top,
            _ => BarPlace::Bottom, // "bottom" or any other value
        }
    }
}

/// The kind of bar to render, controlling which information columns
/// are shown and how the backdrop is styled.
///
/// Corresponds to `overlay_backdrop` from the config.  The master app
/// uses this to set the window transparency and fill colour.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BarKind {
    /// Solid translucent background with accent text.
    Solid,
    /// Mica/dark glass backend (Windows).
    MicaAlt,
    /// Mica (fallback).
    Mica,
    /// Acrylic/etched glass.
    Acrylic,
    /// Blur (DWM composition required).
    Blur,
}

impl BarKind {
    /// Resolve the bar kind from the config string value.
    pub fn from_cfg(backdrop: &str) -> Self {
        match backdrop {
            "solid" => BarKind::Solid,
            "mica_alt" => BarKind::MicaAlt,
            "mica" => BarKind::Mica,
            "acrylic" => BarKind::Acrylic,
            "blur" => BarKind::Blur,
            _ => BarKind::Solid,
        }
    }
}

/// Runtime state for the overlay window.
///
/// The master creates one instance and passes engine events into it
/// so the overlay can redraw the status dot, level meter, and text.
#[derive(Debug, Clone)]
pub struct OverlayState {
    /// Current engine state text (e.g. "Listening", "Transcribing", "Paused").
    pub state: String,
    /// Whether the microphone is currently active/recording.
    pub recording: bool,
    /// Latest RMS level from the audio engine (0.0 .. 1.0), or None if
    /// no level source is available.
    pub level: Option<f32>,
    /// Config-driven placement.
    pub place: BarPlace,
    /// Config-driven backdrop kind.
    pub kind: BarKind,
    /// Hotkey label shown in the overlay (e.g. "Hold Ctrl+Win anywhere...").
    pub hotkey_hint: String,
    /// Whether the overlay should auto-hide after a period of inactivity.
    pub auto_hide: bool,
}

/// Layout the overlay bar's visual contents.
///
/// Returns a column of elements that show:
/// - Status dot + state text
/// - Optional level meter (if `level` is `Some`)
/// - Hotkey hint
/// - Optional "Open Settings" action
pub fn overlay_view<'a>(
    state: &'a OverlayState,
    palette: &'a Palette,
) -> iced::Element<'a, Message, iced::Theme, iced::Renderer> {
    let p = *palette;
    let mut items: Vec<iced::Element<'a, Message, iced::Theme, iced::Renderer>> = Vec::new();

    // Status dot + state text, led by the mic glyph like the Python bar.
    items.push(icons::svg_handle("mic", p.text).into());
    items.push(widgets::status_dot(&state.state, &p).into());
    items.push(text(&state.state).size(14).color(p.text).into());

    // Separator
    items.push(widgets::divider(&p).into());

    // Level meter if a level source exists
    if let Some(level) = state.level {
        items.push(widgets::level_meter(level, &p).into());
    } else {
        // No live level: render idle meter and note
        items.push(text("Unloaded to save VRAM").size(12).color(p.sub).into());
    }

    // Hotkey hint
    items.push(text(&state.hotkey_hint).size(11).color(p.sub).into());

    column(items)
        .align_x(iced::Alignment::Center)
        .spacing(6)
        .width(Length::Fill)
        .height(Length::Fixed(32.0))
        .into()
}

/// Place the overlay bar on screen per the configured position.
///
/// Returns a `Rectangle` representing the bar's screen-area geometry.
/// The master window should use this to position its frameless iced
/// window above the correct monitor edge.
pub fn place_bar(place: BarPlace, screen: iced::Rectangle) -> iced::Rectangle {
    match place {
        BarPlace::Bottom => iced::Rectangle {
            x: screen.x,
            y: screen.y + screen.height - 32.0,
            width: screen.width,
            height: 32.0,
        },
        BarPlace::Top => iced::Rectangle {
            x: screen.x,
            y: screen.y,
            width: screen.width,
            height: 32.0,
        },
    }
}

// Engine event forwarding: the overlay subscribes to a subset of engine
// events and updates its internal state accordingly. The master app
// should wire the engine's `emit` channel so that the following kinds
// update the overlay state:
//
//   - "state"       -> updates `state` and `recording`
//   - "level"       -> updates `level` (RMS 0..1, or None if unloaded)
//   - "hotkey"      -> updates `hotkey_hint`
//
// The overlay does NOT emit events back into the engine; it is purely
// a read-only view layer.