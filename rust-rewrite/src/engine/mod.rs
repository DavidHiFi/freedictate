use crate::config::Config;
use crate::ducking;

pub struct Engine {
    pub cfg: Config,
}

impl Engine {
    pub fn new(cfg: Config) -> Self {
        Self { cfg }
    }

    pub fn start(&mut self) {
        todo!("start hotkey polling and model loading")
    }

    pub fn begin(&mut self, exclusive: bool) {
        let _ = exclusive;
        if self.cfg.bool_value("isolate_output_while_dictating") {
            if let Err(_e) = ducking::start(self.cfg.number_value("isolate_output_level")) {
                // Output isolation is best effort; dictation must still work.
            }
        }
        todo!("start capture and transcription")
    }

    pub fn end(&mut self, cancelled: bool) {
        let _ = cancelled;
        ducking::stop();
    }
}
