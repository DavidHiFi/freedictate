//! Port of src/freedictate/ui/icons.py: the 24x24 stroke icons and their
//! names, rendered into SVG bytes for iced's Svg widget. The Python app
//! strokes the paths in the theme colour; the same string goes to resvg
//! here, with the fill left off exactly like the original.

use iced::widget::svg::{Handle, Svg};
use iced::Color;

/// The 24x24 stroke bodies, byte-identical to the _SVG table in icons.py.
const TABLE: &[(&str, &str)] = &[
    ("mic", r#"<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M8.5 21h7"/>"#),
    ("keyboard", r#"<rect x="2.5" y="6" width="19" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/>"#),
    ("cpu", r#"<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9.5 9.5h5v5h-5zM9 2.5V6M15 2.5V6M9 18v3.5M15 18v3.5M2.5 9H6M2.5 15H6M18 9h3.5M18 15h3.5"/>"#),
    ("text", r#"<path d="M4 6h16M4 10h10M4 14h16M4 18h10"/>"#),
    ("palette", r#"<path d="M12 3a9 9 0 1 0 0 18c1.1 0 1.7-.8 1.7-1.7 0-.5-.2-.9-.5-1.2a1.6 1.6 0 0 1 1.2-2.7H16a5 5 0 0 0 5-5c0-4.1-4-7.4-9-7.4z"/><circle cx="7.5" cy="11" r="1"/><circle cx="10" cy="7" r="1"/><circle cx="14.5" cy="7" r="1"/>"#),
    ("clock", r#"<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>"#),
    ("info", r#"<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>"#),
    ("sliders", r#"<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>"#),
    ("home", r#"<path d="M4 11l8-6 8 6v8a1 1 0 0 1-1 1h-4v-6h-6v6H5a1 1 0 0 1-1-1z"/>"#),
    ("undo", r#"<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>"#),
    ("copy", r#"<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>"#),
    ("trash", r#"<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>"#),
    ("search", r#"<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>"#),
    ("download", r#"<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>"#),
    ("check", r#"<path d="M5 12.5l4.5 4.5L19 7.5"/>"#),
    ("x", r#"<path d="M6 6l12 12M18 6L6 18"/>"#),
    ("file", r#"<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>"#),
    ("refresh", r#"<path d="M20 12a8 8 0 0 1-14.3 5M4 12a8 8 0 0 1 14.3-5M18 3v4h-4M6 21v-4h4"/>"#),
    ("external", r#"<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>"#),
    ("pause", r#"<path d="M9 5v14M15 5v14"/>"#),
    ("play", r#"<path d="M7 5l12 7-12 7z"/>"#),
    ("chevron-down", r#"<path d="M6 9l6 6 6-6"/>"#),
    ("minimize", r#"<path d="M5 12h14"/>"#),
    ("maximize", r#"<rect x="5" y="5" width="14" height="14" rx="1.5"/>"#),
    ("restore", r#"<rect x="5" y="8" width="11" height="11" rx="1.5"/><path d="M8 5h9.5A1.5 1.5 0 0 1 19 6.5V16"/>"#),
    ("close", r#"<path d="M6 6l12 12M18 6L6 18"/>"#),
    ("plus", r#"<path d="M12 5v14M5 12h14"/>"#),
    ("gpu", r#"<rect x="2.5" y="7" width="19" height="10" rx="2"/><circle cx="9" cy="12" r="2.5"/><path d="M15 10.5h3M15 13.5h3M6 17v2.5M10 17v2.5"/>"#),
];

/// Every icon name in the table, for menus that enumerate them. Used by the
/// unit tests; more pages adopt it as they take up glyphs.
#[cfg_attr(not(test), allow(dead_code))]
pub fn names() -> Vec<&'static str> {
    TABLE.iter().map(|(name, _)| *name).collect()
}

/// The icon rendered as an SVG document, stroked in `color` at the same
/// 1.6 width as the original. Unknown names return empty bytes, which iced
/// renders as nothing rather than failing.
pub fn svg_bytes(name: &str, color: Color) -> Vec<u8> {
    let Some((_, body)) = TABLE.iter().find(|(n, _)| *n == name) else {
        return Vec::new();
    };
    let svg = format!(
        r#"<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{stroke}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">{body}</svg>"#,
        stroke = stroke_color(color),
    );
    svg.into_bytes()
}

/// An Svg widget with the named icon stroked in the palette colour.
pub fn svg_handle<'a>(name: &str, color: Color) -> Svg<'a> {
    Svg::new(Handle::from_memory(svg_bytes(name, color)))
}

/// CSS colour for the stroke: opaque colours as #rrggbb, others as rgba().
fn stroke_color(color: Color) -> String {
    let (r, g, b) = (
        (color.r * 255.0).round() as u8,
        (color.g * 255.0).round() as u8,
        (color.b * 255.0).round() as u8,
    );
    if color.a >= 1.0 {
        format!("#{r:02x}{g:02x}{b:02x}")
    } else {
        format!("rgba({r},{g},{b},{:.3})", color.a)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn known_names_render_svg() {
        for name in names() {
            let bytes = svg_bytes(name, Color::BLACK);
            let text = String::from_utf8(bytes).unwrap();
            assert!(text.starts_with("<svg "), "icon {name} produced no svg");
            assert!(
                text.contains(r##"stroke="#000000""##),
                "icon {name} lost its stroke"
            );
        }
    }

    #[test]
    fn unknown_name_is_empty() {
        assert!(svg_bytes("nope", Color::BLACK).is_empty());
    }
}
