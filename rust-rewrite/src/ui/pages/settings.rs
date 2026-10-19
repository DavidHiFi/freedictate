//! The settings page. SHIM: delegates to the legacy view in mod.rs until
//! the Fluent rebuild lands; the owning agent replaces this file and then
//! mod.rs drops the legacy method.
use crate::ui::{App, Element};

pub fn view(app: &App) -> Element<'_> {
    app.settings_view()
}
