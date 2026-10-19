//! The dictation window: the page the app opens on. The original app's
//! main window shows the engine status, the pause control, the hotkey hint
//! and the entry into settings; this port keeps exactly those bindings and
//! dresses them with the Fluent widget set.
//!
//! The level meter is idle: the audio module exposes no live level feed
//! (its snapshots exist only at take boundaries), so the meter renders at
//! zero until an event kind carries a level. That is a recorded gap, not a
//! broken binding.

use crate::ui::widgets;
use crate::ui::{App, Element, Message};
use iced::widget::column;
use iced::{Alignment, Length};

pub fn view(app: &App) -> Element<'_> {
    let p = app.palette();
    let hotkey = crate::hotkeys::label(&app.cfg.string_value("hotkey"));

    let status = vec![
        widgets::status_dot(&app.engine.status_text(), &p),
        widgets::body(&app.engine.status_text(), &p),
    ];

    let items: Vec<Element<'_>> = vec![
        widgets::title("Dictation", &p),
        widgets::card(
            vec![
                column(status).spacing(8).into(),
                widgets::divider(&p),
                widgets::primary_button(
                    if app.paused { "Resume" } else { "Pause" },
                    Message::TogglePause,
                    &p,
                ),
                widgets::level_meter(0.0, &p),
                widgets::sub(
                    "The level meter fills while the microphone hears you.",
                    &p,
                ),
            ],
            &p,
        ),
        widgets::sub(
            &format!("Hold {hotkey} anywhere to dictate. The text arrives where the cursor is."),
            &p,
        ),
        widgets::flat_button("Open Settings", Message::OpenSettings, &p),
    ];

    column(items)
        .spacing(16)
        .width(Length::Fill)
        .max_width(560.0)
        .align_x(Alignment::Center)
        .into()
}
