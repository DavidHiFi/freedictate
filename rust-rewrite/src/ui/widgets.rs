//! The Fluent widget set of the Python app (widgets.py): Banner, Card,
//! Row, Segmented, Combo, Toggle, sliders, StatusDot, LevelMeter, NavButton
//! and the text/button helpers. Every builder takes the active palette and
//! returns an element styled from its roles.
//!
//! The public signatures are the UI contract: pages build with these, so the
//! Fluent internals can be refined without touching the page code.
//!
//! The builders are dead until the pages are rebuilt on them; that allow
//! comes off with the shims.

#![allow(dead_code)]

use iced::widget::{button, column, container, pick_list, row, slider, text, text_input, toggler};
use iced::{Background, Border, Color, Length, Pixels, Padding};
use iced::border::Radius;

use crate::ui::options::Choice;
use crate::ui::theme::{self, Palette};

/// An element in the app renderer.
pub type Elem<'a, T> = iced::Element<'a, T, iced::Theme, iced::Renderer>;

// ------------------------------------------------------------- text helpers

/// Page title, 20pt semibold (QLabel role="title").
pub fn title<'a, T: Clone + 'a>(s: &str, p: &Palette) -> Elem<'a, T> {
    colored_text(s, 27.0, p.text)
}

/// Section heading inside a card, 11pt semibold (role="section").
pub fn section<'a, T: Clone + 'a>(s: &str, p: &Palette) -> Elem<'a, T> {
    colored_text(s, 15.0, p.text)
}

/// Row title, 14pt semibold (role="name").
pub fn name_label<'a, T: Clone + 'a>(s: &str, p: &Palette) -> Elem<'a, T> {
    colored_text(s, 19.0, p.text)
}

/// Body text, 10.5pt (role="rowtitle").
pub fn body<'a, T: Clone + 'a>(s: &str, p: &Palette) -> Elem<'a, T> {
    colored_text(s, 14.0, p.text)
}

/// Secondary text, 9.5pt in the sub colour (role="sub").
pub fn sub<'a, T: Clone + 'a>(s: &str, p: &Palette) -> Elem<'a, T> {
    colored_text(s, 13.0, p.sub)
}

/// Warn-tinted secondary text (role="warn").
pub fn warn_text<'a, T: Clone + 'a>(s: &str, p: &Palette) -> Elem<'a, T> {
    colored_text(s, 13.0, p.warn)
}

/// Ok-tinted secondary text (role="ok").
pub fn ok_text<'a, T: Clone + 'a>(s: &str, p: &Palette) -> Elem<'a, T> {
    colored_text(s, 13.0, p.ok)
}

/// Danger-tinted secondary text (role="danger").
pub fn danger_text<'a, T: Clone + 'a>(s: &str, p: &Palette) -> Elem<'a, T> {
    colored_text(s, 13.0, p.danger)
}

fn colored_text<'a, T: Clone + 'a>(s: &str, size: f32, color: Color) -> Elem<'a, T> {
    text(s.to_string())
        .size(size)
        .style(move |_| iced::widget::text::Style {
            color: Some(color),
        })
        .into()
}

/// A 1px divider in the line role (QFrame#divider).
pub fn divider<'a, T: Clone + 'a>(p: &Palette) -> Elem<'a, T> {
    let p = *p;
    container(text(""))
        .height(1.0)
        .width(Length::Fill)
        .style(move |_| container::Style {
            background: Some(Background::Color(theme::with_alpha(p.line, 0.6))),
            ..Default::default()
        })
        .into()
}

// ------------------------------------------------------------- containers

/// The Card: a surface-radius-8 container holding rows and captions
/// (QFrame#card + widgets.Card).
pub fn card<'a, T: Clone + 'a>(children: Vec<Elem<'a, T>>, p: &Palette) -> Elem<'a, T> {
    let p = *p;
    container(column(children).spacing(10))
        .width(Length::Fill)
        .padding(14)
        .style(move |_| container::Style {
            background: Some(Background::Color(p.surface)),
            border: Border {
                radius: 8.0.into(),
                ..Default::default()
            },
            ..Default::default()
        })
        .into()
}

/// The Row: a title with an optional description and a control on the right
/// (widgets.Row). The description sits under the title in the sub colour.
pub fn row_item<'a, T: Clone + 'a>(
    title_text: &str,
    desc: &str,
    control: Option<Elem<'a, T>>,
    p: &Palette,
) -> Elem<'a, T> {
    let p = *p;
    let mut label_column = column(vec![name_label(title_text, &p)]);
    if !desc.is_empty() {
        label_column = label_column.push(sub(desc, &p));
    }
    let mut items: Vec<Elem<'a, T>> = vec![label_column.width(Length::Fill).into()];
    if let Some(control) = control {
        items.push(control);
    }
    row(items)
        .align_y(iced::Alignment::Center)
        .spacing(12)
        .width(Length::Fill)
        .into()
}

/// The Banner: an accent-tinted notice, or warn-tinted when warn is set
/// (QFrame#banner / bannerWarn).
pub fn banner<'a, T: Clone + 'a>(s: &str, warn: bool, p: &Palette) -> Elem<'a, T> {
    let p = *p;
    let (bg, border) = if warn {
        (
            theme::with_alpha(p.warn, 0.14),
            theme::with_alpha(p.warn, 0.45),
        )
    } else {
        (
            theme::with_alpha(p.accent, 0.16),
            theme::with_alpha(p.accent, 0.45),
        )
    };
    container(body(s, &p))
        .width(Length::Fill)
        .padding([10, 12])
        .style(move |_| container::Style {
            background: Some(Background::Color(bg)),
            border: Border {
                radius: 8.0.into(),
                width: 1.0,
                color: border,
            },
            ..Default::default()
        })
        .into()
}

// ------------------------------------------------------------- buttons

fn button_base<'a, T: Clone + 'a>(
    label: &str,
    on_press: T,
    p: &Palette,
    pick: impl Fn(button::Status) -> (Color, Color, Color) + 'a,
) -> Elem<'a, T> {
    let p = *p;
    button(colored_text(label, 14.0, p.text))
        .padding([6, 14])
        .style(move |_, status| {
            let (background, text_color, border) = pick(status);
            button::Style {
                background: Some(Background::Color(background)),
                text_color,
                border: Border {
                    radius: 6.0.into(),
                    width: 1.0,
                    color: border,
                },
                ..Default::default()
            }
        })
        .on_press(on_press)
        .into()
}

/// The plain Fluent button: field background, hairline border, hover/press
/// states from the palette (QPushButton).
pub fn flat_button<'a, T: Clone + 'a>(label: &str, on_press: T, p: &Palette) -> Elem<'a, T> {
    let p = *p;
    button_base(label, on_press, &p, move |status| {
        let bg = match status {
            button::Status::Hovered => p.hover,
            button::Status::Pressed => p.press,
            _ => p.field,
        };
        (bg, p.text, theme::with_alpha(p.line, 0.9))
    })
}

/// The primary button: accent background, on_accent label, semibold
/// (QPushButton[kind="primary"]).
pub fn primary_button<'a, T: Clone + 'a>(label: &str, on_press: T, p: &Palette) -> Elem<'a, T> {
    let p = *p;
    let hover = theme::mix(p.accent, p.text, 0.18);
    let press = theme::mix(p.accent, p.bg, 0.2);
    button_base(label, on_press, &p, move |status| {
        let bg = match status {
            button::Status::Hovered => hover,
            button::Status::Pressed => press,
            _ => p.accent,
        };
        (bg, p.on_accent, p.accent)
    })
}

/// The danger button: normal until hovered, then a danger tint with a danger
/// border (QPushButton[kind="danger"]).
pub fn danger_button<'a, T: Clone + 'a>(label: &str, on_press: T, p: &Palette) -> Elem<'a, T> {
    let p = *p;
    button_base(label, on_press, &p, move |status| {
        match status {
            button::Status::Hovered | button::Status::Pressed => {
                (theme::with_alpha(p.danger, 0.22), p.text, p.danger)
            }
            _ => (p.field, p.text, theme::with_alpha(p.line, 0.9)),
        }
    })
}

/// The flat button: transparent until hovered (QPushButton[kind="flat"]).
pub fn link_button<'a, T: Clone + 'a>(label: &str, on_press: T, p: &Palette) -> Elem<'a, T> {
    let p = *p;
    button(colored_text(label, 14.0, p.accent))
        .padding([2, 0])
        .style(move |_, _| button::Style {
            background: None,
            text_color: p.accent,
            border: Border {
                radius: 6.0.into(),
                ..Default::default()
            },
            ..Default::default()
        })
        .on_press(on_press)
        .into()
}

/// One entry of the nav rail: icon glyph plus label, filled when selected
/// (window.py NavButton).
pub fn nav_button<'a, T: Clone + 'a>(
    label: &str,
    glyph: &str,
    selected: bool,
    on_press: T,
    p: &Palette,
) -> Elem<'a, T> {
    let p = *p;
    let fg = if selected { p.accent } else { p.text };
    let content = row(vec![
        colored_text(glyph, 15.0, fg),
        colored_text(label, 14.0, fg),
    ])
    .spacing(8);
    button(content)
        .width(Length::Fill)
        .padding([8, 12])
        .style(move |_, status| {
            let background = if selected {
                Some(Background::Color(p.surface))
            } else if matches!(status, button::Status::Hovered) {
                Some(Background::Color(theme::with_alpha(p.hover, 0.6)))
            } else {
                None
            };
            button::Style {
                background,
                text_color: fg,
                border: Border {
                    radius: 6.0.into(),
                    ..Default::default()
                },
                ..Default::default()
            }
        })
        .on_press(on_press)
        .into()
}

// ------------------------------------------------------------- controls

/// The animated on/off switch of the Python app (widgets.Toggle). The knob
/// animation is the agent's slice; the contract is checked + on_toggle.
/// 
/// Python: 44x22 track, 10px knob (12px hover), rounded pill track.
/// In iced: toggler size=22 gives track ~44x22, knob 10px (12px hover).
pub fn toggle<'a, T: Clone + 'a>(
    checked: bool,
    on_toggle: impl Fn(bool) -> T + 'a,
    p: &Palette,
) -> Elem<'a, T> {
    let p = *p;
    toggler(checked)
        .on_toggle(on_toggle)
        .size(22.0)
        .style(move |_theme: &iced::Theme, status| {
            let accent = p.accent;
            let on_accent = p.on_accent;
            let line = p.line;
            let sub = p.sub;
            let hover = p.hover;
            let field = p.field;
            let text = p.text;

            let (is_toggled, is_hovered, is_disabled) = match status {
                toggler::Status::Active { is_toggled } => (is_toggled, false, false),
                toggler::Status::Hovered { is_toggled } => (is_toggled, true, false),
                toggler::Status::Disabled { is_toggled } => (is_toggled, false, true),
            };

            // Background (track)
            let (background, background_border_width, background_border_color) = if is_toggled {
                if is_disabled {
                    (theme::with_alpha(accent, 0.4).into(), 0.0, Color::TRANSPARENT)
                } else if is_hovered {
                    (theme::mix(accent, text, 0.15).into(), 0.0, Color::TRANSPARENT)
                } else {
                    (accent.into(), 0.0, Color::TRANSPARENT)
                }
            } else {
                if is_disabled {
                    (field.into(), 1.2, theme::with_alpha(sub, 0.4))
                } else if is_hovered {
                    (theme::with_alpha(hover, 0.5).into(), 1.2, theme::with_alpha(line, 0.9))
                } else {
                    (Background::Color(Color::TRANSPARENT), 1.2, theme::with_alpha(line, 0.9))
                }
            };

            // Foreground (knob)
            let knob_color = if is_toggled {
                on_accent
            } else if is_disabled {
                theme::with_alpha(sub, 0.5)
            } else {
                sub
            };
            // Knob grows from 10 to 12 on hover (Python: d = 12 if hover else 10)
            // padding_ratio = padding / height. Track height = size = 22.
            // Knob diameter = height - 2*padding. For 10px knob: padding = (22-10)/2 = 6. ratio = 6/22 ≈ 0.273
            // For 12px knob: padding = (22-12)/2 = 5. ratio = 5/22 ≈ 0.227
            let padding_ratio = if is_hovered && !is_disabled { 5.0 / 22.0 } else { 6.0 / 22.0 };

            toggler::Style {
                background,
                background_border_width,
                background_border_color,
                foreground: Background::Color(knob_color),
                foreground_border_width: 0.0,
                foreground_border_color: Color::TRANSPARENT,
                text_color: None,
                border_radius: None, // perfectly round (height/2)
                padding_ratio,
            }
        })
        .into()
}

/// The segmented control: joined pills where the checked one is accent
/// (QPushButton[kind="segment"]). options is (key, label) pairs.
pub fn segmented<'a, T: Clone + 'a>(
    options: &'a [(&'a str, &'a str)],
    value: &str,
    on_select: impl Fn(String) -> T + Clone + 'a,
    p: &Palette,
) -> Elem<'a, T> {
    let p = *p;
    let n = options.len();
    let buttons: Vec<Elem<'a, T>> = options
        .iter()
        .enumerate()
        .map(|(i, (key, label))| {
            let selected = *key == value;
            let is_first = i == 0;
            let is_last = i == n - 1;
            let fg = if selected { p.on_accent } else { p.text };
            let bg = if selected { p.accent } else { p.field };
            let border_color = if selected { p.accent } else { theme::with_alpha(p.line, 0.9) };
            let hover_bg = if selected { p.accent } else { p.hover };
            let press_bg = if selected { p.accent } else { p.press };
            let key = key.to_string();

            // Build radius: first gets left radius, last gets right radius, middle gets none
            let radius = if is_first && is_last {
                6.0.into() // single segment - fully rounded
            } else if is_first {
                Radius {
                    top_left: 6.0,
                    top_right: 0.0,
                    bottom_right: 0.0,
                    bottom_left: 6.0,
                }
            } else if is_last {
                Radius {
                    top_left: 0.0,
                    top_right: 6.0,
                    bottom_right: 6.0,
                    bottom_left: 0.0,
                }
            } else {
                Radius::default()
            };

            button(colored_text(label, 13.0, fg))
                .padding([6, 12])
                .style(move |_, status| {
                    let background = match status {
                        button::Status::Hovered if !selected => hover_bg,
                        button::Status::Pressed if !selected => press_bg,
                        _ => bg,
                    };
                    button::Style {
                        background: Some(Background::Color(background)),
                        text_color: fg,
                        border: Border {
                            radius,
                            width: 1.0,
                            color: border_color,
                        },
                        ..Default::default()
                    }
                })
                .on_press(on_select.clone()(key))
                .into()
        })
        .collect();
    row(buttons).spacing(0).into()
}

/// The dropdown (widgets.Combo): items as (key, label) pairs, the saved key
/// preselected, the chosen key handed back.
/// 
/// QSS: QComboBox field bg, 1px line border radius 6, hover state,
/// dropdown menu surface background (0.55 alpha), items ~30px, selection accent 0.25.
pub fn combo<'a, T: Clone + 'a>(
    options: Vec<Choice>,
    selected: Option<Choice>,
    on_select: impl Fn(String) -> T + Clone + 'a,
    p: &Palette,
) -> Elem<'a, T> {
    let p = *p;
    pick_list(options, selected, move |choice: Choice| {
        on_select.clone()(choice.key)
    })
    .width(Length::Fixed(240.0))
    .text_size(Pixels(14.0))
    .padding(Padding::new(5.0).right(30.0).left(10.0))
    .style(move |_theme: &iced::Theme, status| {
        let active = pick_list::Style {
            text_color: p.text,
            placeholder_color: p.sub,
            handle_color: p.sub,
            background: Background::Color(p.field),
            border: Border {
                radius: 6.0.into(),
                width: 1.0,
                color: theme::with_alpha(p.line, 0.9),
            },
        };

        match status {
            pick_list::Status::Active => active,
            pick_list::Status::Hovered => pick_list::Style {
                background: Background::Color(p.hover),
                ..active
            },
            pick_list::Status::Opened { .. } => pick_list::Style {
                border: Border {
                    color: p.accent,
                    ..active.border
                },
                ..active
            },
        }
    })
    .menu_style(move |_theme: &iced::Theme| {
        // Menu styling for the dropdown list
        iced::widget::overlay::menu::Style {
            background: Background::Color(theme::with_alpha(p.surface, 0.55)),
            border: Border {
                radius: 6.0.into(),
                width: 0.0,
                color: Color::TRANSPARENT,
            },
            text_color: p.text,
            selected_text_color: p.text,
            selected_background: Background::Color(theme::with_alpha(p.accent, 0.25)),
            shadow: iced::Shadow::default(),
        }
    })
    .into()
}

/// The hotkey box (widgets.HotkeyEdit): a single-line field that reports
/// each keystroke so the app can validate + save.
/// 
/// QSS: QLineEdit field bg, line border radius 6, darker bottom border (sub),
/// focus moves bottom border to 2px accent.
pub fn hotkey_edit<'a, T: Clone + 'a>(
    value: &str,
    on_input: impl Fn(String) -> T + Clone + 'a,
    p: &Palette,
) -> Elem<'a, T> {
    let p = *p;
    text_input("Ctrl + Win", value)
        .on_input(move |s| on_input.clone()(s))
        .size(14)
        .width(Length::Fixed(220.0))
        .padding(Padding::new(5.0).horizontal(9.0))
        .style(move |_theme: &iced::Theme, status| {
            let active = text_input::Style {
                background: Background::Color(p.field),
                border: Border {
                    radius: 6.0.into(),
                    width: 1.0,
                    color: theme::with_alpha(p.line, 0.9),
                },
                placeholder: p.sub,
                value: p.text,
                selection: p.accent,
                icon: p.sub,
            };

            match status {
                text_input::Status::Active => active,
                text_input::Status::Hovered => text_input::Style {
                    border: Border {
                        color: theme::with_alpha(p.line, 1.0),
                        ..active.border
                    },
                    ..active
                },
                text_input::Status::Focused { .. } => text_input::Style {
                    border: Border {
                        color: p.accent,
                        width: 2.0, // Focus: 2px accent border (simulated via full border)
                        ..active.border
                    },
                    ..active
                },
                text_input::Status::Disabled => text_input::Style {
                    background: Background::Color(theme::with_alpha(p.field, 0.4)),
                    value: theme::with_alpha(p.text, 0.4),
                    placeholder: theme::with_alpha(p.text, 0.4),
                    icon: theme::with_alpha(p.text, 0.4),
                    border: Border {
                        color: theme::with_alpha(p.line, 0.4),
                        ..active.border
                    },
                    ..active
                },
            }
        })
        .into()
}

/// The styled slider: 4px rail, accent fill, round handle (QSlider). The
/// on_release message fires when the drag ends, like the Python save-on-release.
/// 
/// QSS: 4px groove in line color radius 2, accent sub-page fill,
/// ~12px round accent handle with 4px ring of mix(surface, bg, 0.3),
/// hover ring accent at 0.4 alpha.
pub fn styled_slider<'a, T: Clone + 'a>(
    range: std::ops::RangeInclusive<f32>,
    value: f32,
    on_change: impl Fn(f32) -> T + Clone + 'a,
    on_release: T,
    p: &Palette,
) -> Elem<'a, T> {
    let p = *p;
    let handle_radius = 6.0; // 12px diameter
    let ring_width = 4.0;
    let ring_color = theme::mix(p.surface, p.bg, 0.3);
    let hover_ring_color = theme::with_alpha(p.accent, 0.4);

    slider(range, value, move |v| on_change.clone()(v))
        .on_release(on_release)
        .width(Length::Fixed(220.0))
        .height(22.0) // Match QSlider min-height: 22px
        .style(move |_theme: &iced::Theme, status| {
            let rail_color = match status {
                slider::Status::Active => p.accent,
                slider::Status::Hovered => p.accent,
                slider::Status::Dragged => p.accent,
            };
            let handle_color = match status {
                slider::Status::Active => p.accent,
                slider::Status::Hovered => p.accent,
                slider::Status::Dragged => p.accent,
            };
            let handle_border_color = match status {
                slider::Status::Hovered | slider::Status::Dragged => hover_ring_color,
                _ => ring_color,
            };
            let handle_border_width = match status {
                slider::Status::Hovered | slider::Status::Dragged => 5.0, // margin -9px, border 5px
                _ => ring_width, // margin -8px, border 4px
            };

            slider::Style {
                rail: slider::Rail {
                    backgrounds: (
                        Background::Color(rail_color),      // filled (sub-page)
                        Background::Color(theme::with_alpha(p.line, 1.0)), // unfilled (groove)
                    ),
                    width: 4.0,
                    border: Border {
                        radius: 2.0.into(),
                        width: 0.0,
                        color: Color::TRANSPARENT,
                    },
                },
                handle: slider::Handle {
                    shape: slider::HandleShape::Circle { radius: handle_radius },
                    background: Background::Color(handle_color),
                    border_width: handle_border_width,
                    border_color: handle_border_color,
                },
            }
        })
        .into()
}

/// The small status dot: ok when ready, warn when busy, danger while
/// recording (app.py's StatusDot).
pub fn status_dot<'a, T: Clone + 'a>(state: &str, p: &Palette) -> Elem<'a, T> {
    let p = *p;
    let color = match state {
        "recording" => p.danger,
        "loading" | "downloading" | "busy" => p.warn,
        "unloaded" | "idle" => p.sub,
        _ => p.ok,
    };
    container(text(""))
        .width(10.0)
        .height(10.0)
        .style(move |_| container::Style {
            background: Some(Background::Color(color)),
            border: Border {
                radius: 5.0.into(),
                ..Default::default()
            },
            ..Default::default()
        })
        .into()
}

/// The mic level meter of the dictation page: a 4px rail with the accent
/// portion showing the current level (0.0..=1.0), like the Python LevelMeter.
/// 
/// Python paintEvent: 8px high (fixed), line-color rail radius 3,
/// accent fill (ok below 0.85, warn above), peak marker 2px wide text@0.6.
pub fn level_meter<'a, T: Clone + 'a>(level: f32, p: &Palette) -> Elem<'a, T> {
    let p = *p;
    let filled = level.clamp(0.0, 1.0) * 240.0;
    let fill_color = if level < 0.85 { p.ok } else { p.warn };
    
    container(
        container(text(""))
            .width(Length::Fixed(filled))
            .height(4.0)
            .style(move |_| container::Style {
                background: Some(Background::Color(fill_color)),
                border: Border {
                    radius: 2.0.into(),
                    ..Default::default()
                },
                ..Default::default()
            }),
    )
    .width(Length::Fixed(240.0))
    .height(8.0) // Python: 8px fixed height
    .style(move |_| container::Style {
        background: Some(Background::Color(p.line)),
        border: Border {
            radius: 2.0.into(),
            ..Default::default()
        },
        ..Default::default()
    })
    .into()
}