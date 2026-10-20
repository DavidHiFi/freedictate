//! The window icon at runtime. The exe already carries the FreeDictate icon
//! for Explorer and the taskbar; iced still wants pixels for the window it
//! owns, so this decodes the same embedded .ico and hands the largest
//! frame to the window settings.

/// The taskbar/Alt-tab icon for the window iced owns; the exe resource only
/// covers Explorer's view. Falls back to iced's default when the asset
/// would not decode.
pub(crate) fn window_icon() -> Option<iced::window::Icon> {
    let data: &[u8] =
        include_bytes!(concat!(env!("CARGO_MANIFEST_DIR"), "/../assets/freedictate.ico"));
    iced::window::icon::from_file_data(data, None).ok()
}
