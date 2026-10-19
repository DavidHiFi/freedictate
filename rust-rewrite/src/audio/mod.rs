pub fn refresh_devices() {
    todo!("list capture and playback devices")
}

pub struct Recorder {
    device_name: String,
    exclusive: bool,
}

impl Recorder {
    pub fn start(&mut self, device_name: &str, exclusive: bool) {
        self.device_name = device_name.to_string();
        self.exclusive = exclusive;
        todo!("start capture, optionally exclusive")
    }

    pub fn stop(&mut self) {
        todo!("stop capture and release the mic")
    }
}
