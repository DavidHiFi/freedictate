pub struct Engine {
    cfg: crate::config::Config,
}

impl Engine {
    pub fn start(&mut self) {
        todo!("start hotkey polling and model loading")
    }

    pub fn begin(&mut self, exclusive: bool) {
        todo!("start a take")
    }

    pub fn end(&mut self, cancelled: bool) {
        todo!("end a take and restore audio")
    }
}
