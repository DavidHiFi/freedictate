pub struct Config {
    pub path: std::path::PathBuf,
}

impl Config {
    pub fn load() -> Self {
        todo!("read settings.json")
    }

    pub fn save(&self) {
        todo!("write settings.json")
    }

    pub fn update(&mut self, _values: &str) {
        todo!("apply a settings change")
    }
}
