//! Live microphone level for the UI. A subscription polls the audio
//! module's process-wide level at ~50 ms and raises `Message::Level`, so
//! the dictation meter and the settings mic meter move while the app hears
//! you and rest at zero between takes.

use crate::ui::Message;
use crate::audio;
use std::time::Duration;

/// How often the level is sampled for the meters.
const METER_POLL: Duration = Duration::from_millis(50);

/// The polling loop as a stream, mirroring the events_stream trick in
/// ui/mod.rs: a std sleep parks ~50 ms per sample and every sample becomes
/// one `Message::Level`. No executor-specific timer API anywhere.
fn level_stream() -> impl iced::futures::Stream<Item = Message> {
    iced::stream::channel(
        32,
        |out: iced::futures::channel::mpsc::Sender<Message>| async move {
            use iced::futures::SinkExt as _;
            let mut out = out;
            loop {
                std::thread::sleep(METER_POLL);
                let _ = out.send(Message::Level(audio::live_level())).await;
            }
        },
    )
}

pub fn subscribe() -> iced::Subscription<Message> {
    iced::Subscription::run(level_stream)
}
