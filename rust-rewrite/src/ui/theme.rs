//! Palettes and theme resolution, ported from src/freedictate/ui/theme.py.
//!
//! Each palette defines roles, not raw widget colours: bg (window), surface
//! (cards), field (inputs), hover, press, line (dividers and borders), text,
//! sub (secondary text), accent, on_accent, warn, danger, ok, and dark (the
//! tone Windows chrome should take). The seeded values are the exact hex
//! pairs of the Python app; `effective` adds the Windows accent override.

use iced::Color;

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Palette {
    pub name: &'static str,
    pub dark: bool,
    pub bg: Color,
    pub surface: Color,
    pub field: Color,
    pub hover: Color,
    pub press: Color,
    pub line: Color,
    pub text: Color,
    pub sub: Color,
    pub accent: Color,
    pub on_accent: Color,
    pub warn: Color,
    pub danger: Color,
    pub ok: Color,
}

/// (name, dark, [bg, surface, field, hover, press, line, text, sub, accent,
/// on_accent, warn, danger, ok]) — the Python PALETTES table, byte for byte.
const TABLE: &[(&str, bool, [u32; 13])] = &[
    (
        "Catppuccin Mocha",
        true,
        [0x1e1e2e, 0x181825, 0x11111b, 0x313244, 0x45475a, 0x313244, 0xcdd6f4, 0xbac2de, 0x89b4fa, 0x11111b, 0xf9e2af, 0xf38ba8, 0xa6e3a1],
    ),
    (
        "Catppuccin Macchiato",
        true,
        [0x24273a, 0x363a4f, 0x494d64, 0x5b6078, 0x6e738d, 0x494d64, 0xcad3f5, 0xa5adcb, 0x8aadf4, 0x181926, 0xeed49f, 0xed8796, 0xa6da95],
    ),
    (
        "Catppuccin Frappe",
        true,
        [0x303446, 0x414559, 0x51576d, 0x626880, 0x737994, 0x51576d, 0xc6d0f5, 0xa5adce, 0x8caaee, 0x232634, 0xe5c890, 0xe78284, 0xa6d189],
    ),
    (
        "Catppuccin Latte",
        false,
        [0xeff1f5, 0xe6e9ef, 0xccd0da, 0xbcc0cc, 0xacb0be, 0xccd0da, 0x4c4f69, 0x5c5f77, 0x1e66f5, 0xffffff, 0xdf8e1d, 0xd20f39, 0x40a02b],
    ),
    (
        "Tokyo Night",
        true,
        [0x1a1b26, 0x24283b, 0x2f3549, 0x3b4261, 0x545c7e, 0x3b4261, 0xc0caf5, 0xa9b1d6, 0x7aa2f7, 0x16161e, 0xe0af68, 0xf7768e, 0x9ece6a],
    ),
    (
        "Nord",
        true,
        [0x2e3440, 0x3b4252, 0x434c5e, 0x4c566a, 0x616e88, 0x4c566a, 0xeceff4, 0xd8dee9, 0x88c0d0, 0x2e3440, 0xebcb8b, 0xbf616a, 0xa3be8c],
    ),
    (
        "Rose Pine",
        true,
        [0x191724, 0x1f1d2e, 0x26233a, 0x403d52, 0x524f67, 0x403d52, 0xe0def4, 0x908caa, 0xc4a7e7, 0x191724, 0xf6c177, 0xeb6f92, 0x9ccfd8],
    ),
    (
        "Dracula",
        true,
        [0x282a36, 0x343746, 0x414458, 0x4d5066, 0x6272a4, 0x44475a, 0xf8f8f2, 0xbfc3d9, 0xbd93f9, 0x1e1f29, 0xf1fa8c, 0xff5555, 0x50fa7b],
    ),
    (
        "Graphite",
        true,
        [0x1c1c1c, 0x2b2b2b, 0x363636, 0x404040, 0x4d4d4d, 0x3a3a3a, 0xf3f3f3, 0xc5c5c5, 0x60cdff, 0x000000, 0xfce100, 0xff99a4, 0x6ccb5f],
    ),
    (
        "Paper",
        false,
        [0xf3f3f3, 0xfbfbfb, 0xffffff, 0xebebeb, 0xdedede, 0xe0e0e0, 0x1b1b1b, 0x5d5d5d, 0x005fb8, 0xffffff, 0x9d5d00, 0xc42b1c, 0x0f7b0f],
    ),
];

/// The "Match Windows" entry and the palette used when nothing matches.
pub const SYSTEM: &str = "Match Windows";

/// The palette used when nothing matches.
#[allow(dead_code)] // theme picker consumes this with the rebuilt pages
pub const DEFAULT_THEME: &str = "Catppuccin Mocha";

/// Menu order: Match Windows first, then the named palettes.
#[allow(dead_code)]
pub fn theme_names() -> Vec<String> {
    let mut names = vec![SYSTEM.to_string()];
    names.extend(TABLE.iter().map(|(name, _, _)| name.to_string()));
    names
}

/// Font stack of the Python app: the configured family, then these.
#[allow(dead_code)] // font picker consumes this with the rebuilt pages
pub const FONT_FALLBACKS: &str = "Segoe UI Variable Text";

fn rgb(hex: u32) -> Color {
    Color::from_rgb8(
        ((hex >> 16) & 0xff) as u8,
        ((hex >> 8) & 0xff) as u8,
        (hex & 0xff) as u8,
    )
}

fn build(name: &'static str, dark: bool, roles: &[u32; 13]) -> Palette {
    Palette {
        name,
        dark,
        bg: rgb(roles[0]),
        surface: rgb(roles[1]),
        field: rgb(roles[2]),
        hover: rgb(roles[3]),
        press: rgb(roles[4]),
        line: rgb(roles[5]),
        text: rgb(roles[6]),
        sub: rgb(roles[7]),
        accent: rgb(roles[8]),
        on_accent: rgb(roles[9]),
        warn: rgb(roles[10]),
        danger: rgb(roles[11]),
        ok: rgb(roles[12]),
    }
}

/// True when Windows draws dark chrome (AppsUseLightTheme == 0). Defaults to
/// dark when the key cannot be read, like the Python app.
pub fn windows_dark() -> bool {
    use windows::Win32::System::Registry::{
        RegCloseKey, RegOpenKeyExW, RegQueryValueExW, HKEY_CURRENT_USER, HKEY,
        KEY_READ, REG_VALUE_TYPE,
    };
    unsafe {
        let mut key = HKEY::default();
        let path: Vec<u16> = "Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize\0"
            .encode_utf16()
            .collect();
        if RegOpenKeyExW(HKEY_CURRENT_USER, windows::core::PCWSTR(path.as_ptr()), None, KEY_READ, &mut key)
            .is_err()
        {
            return true;
        }
        let mut value: u32 = 0;
        let mut size = std::mem::size_of::<u32>() as u32;
        let mut kind = REG_VALUE_TYPE::default();
        let read = RegQueryValueExW(
            key,
            windows::core::w!("AppsUseLightTheme"),
            None,
            Some(&mut kind),
            Some(&mut value as *mut u32 as *mut u8),
            Some(&mut size),
        );
        let _ = RegCloseKey(key);
        if read.is_err() {
            return true;
        }
        value == 0
    }
}

/// The Windows DWM accent colour, if set (0xAABBGGRR registry value).
pub fn windows_accent() -> Option<Color> {
    use windows::Win32::System::Registry::{
        RegCloseKey, RegOpenKeyExW, RegQueryValueExW, HKEY, HKEY_CURRENT_USER, KEY_READ,
        REG_VALUE_TYPE,
    };
    unsafe {
        let mut key = HKEY::default();
        let path: Vec<u16> = "Software\\Microsoft\\Windows\\DWM\0".encode_utf16().collect();
        if RegOpenKeyExW(HKEY_CURRENT_USER, windows::core::PCWSTR(path.as_ptr()), None, KEY_READ, &mut key)
            .is_err()
        {
            return None;
        }
        let mut value: u32 = 0;
        let mut size = std::mem::size_of::<u32>() as u32;
        let mut kind = REG_VALUE_TYPE::default();
        let read = RegQueryValueExW(
            key,
            windows::core::w!("AccentColor"),
            None,
            Some(&mut kind),
            Some(&mut value as *mut u32 as *mut u8),
            Some(&mut size),
        );
        let _ = RegCloseKey(key);
        if read.is_err() {
            return None;
        }
        let (r, g, b) = ((value & 0xff) as u8, ((value >> 8) & 0xff) as u8, ((value >> 16) & 0xff) as u8);
        Some(Color::from_rgb8(r, g, b))
    }
}

/// A named palette, or the system one from the Windows light/dark setting.
pub fn resolve(name: &str) -> Palette {
    if name == SYSTEM {
        return if windows_dark() {
            build("Graphite", true, &TABLE[8].2)
        } else {
            build("Paper", false, &TABLE[9].2)
        };
    }
    let entry = TABLE
        .iter()
        .find(|(n, _, _)| *n == name)
        .unwrap_or(&TABLE[0]);
    build(entry.0, entry.1, &entry.2)
}

/// resolve() plus the Windows accent override: when accent_source is
/// "windows", the palette takes the DWM accent and picks on_accent by
/// luminance, like theme.override_accent.
pub fn effective(theme_name: &str, accent_source: &str) -> Palette {
    let mut p = resolve(theme_name);
    if accent_source == "windows" {
        if let Some(accent) = windows_accent() {
            let lum = 0.2126 * accent.r + 0.7152 * accent.g + 0.0722 * accent.b;
            p.accent = accent;
            p.on_accent = if lum > 0.45 {
                Color::BLACK
            } else {
                Color::WHITE
            };
        }
    }
    p
}

/// Linear mix of two colours, the theme.py mix() helper.
pub fn mix(a: Color, b: Color, t: f32) -> Color {
    Color::from_rgba(
        a.r + (b.r - a.r) * t,
        a.g + (b.g - a.g) * t,
        a.b + (b.b - a.b) * t,
        a.a + (b.a - a.a) * t,
    )
}

/// The same colour with a new alpha (theme.py qc/rgba helpers).
pub fn with_alpha(c: Color, alpha: f32) -> Color {
    Color { a: alpha, ..c }
}

/// The iced theme handed to `application().theme()`: a custom theme built
/// from the palette's six primary roles, so iced's own widgets (pick lists,
/// text inputs, sliders) pick up the palette too.
pub fn to_iced(p: &Palette) -> iced::Theme {
    iced::Theme::custom(
        p.name,
        iced::theme::Palette {
            background: p.bg,
            text: p.text,
            primary: p.accent,
            success: p.ok,
            warning: p.warn,
            danger: p.danger,
        },
    )
}

/// The variant for a window with a live system backdrop: the clear colour
/// goes fully transparent so Mica/Acrylic show through, while painted
/// surfaces keep their own opaque roles.
pub fn to_iced_transparent(p: &Palette) -> iced::Theme {
    iced::Theme::custom(
        p.name,
        iced::theme::Palette {
            background: Color { a: 0.0, ..p.bg },
            text: p.text,
            primary: p.accent,
            success: p.ok,
            warning: p.warn,
            danger: p.danger,
        },
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn palettes_keep_their_names_and_roles() {
        let mocha = resolve("Catppuccin Mocha");
        assert_eq!(mocha.name, "Catppuccin Mocha");
        assert!(mocha.dark);
        assert_eq!(mocha.accent, rgb(0x89b4fa));
        let paper = resolve("Paper");
        assert!(!paper.dark);
    }

    #[test]
    fn unknown_names_fall_back_to_the_default() {
        assert_eq!(resolve("No Such Theme").name, DEFAULT_THEME);
    }

    #[test]
    fn theme_names_lists_system_first() {
        let names = theme_names();
        assert_eq!(names[0], SYSTEM);
        assert!(names.contains(&"Nord".to_string()));
        assert_eq!(names.len(), 11);
    }

    #[test]
    fn mix_walks_between_colours() {
        let a = Color::BLACK;
        let b = Color::WHITE;
        let m = mix(a, b, 0.5);
        assert!((m.r - 0.5).abs() < 1e-6);
    }
}
