use std::cell::{Cell, RefCell};
use windows::core::Interface;

use windows::Win32::Foundation::{RPC_E_CHANGED_MODE, S_FALSE};
use windows::Win32::Media::Audio::{
    eMultimedia, eRender, IAudioSessionControl2, IAudioSessionEnumerator, IAudioSessionManager2,
    IMMDeviceEnumerator, ISimpleAudioVolume, MMDeviceEnumerator,
};
use windows::Win32::System::Com::{
    CoCreateInstance, CoInitializeEx, CLSCTX_ALL, COINIT_MULTITHREADED,
};

struct Saved {
    volume: f32,
    muted: bool,
    control: ISimpleAudioVolume,
}

thread_local! {
    static SAVED: RefCell<Vec<Saved>> = RefCell::new(Vec::new());
    static ACTIVE: Cell<bool> = const { Cell::new(false) };
}

fn ensure_com() -> windows::core::Result<()> {
    let hr = unsafe { CoInitializeEx(None, COINIT_MULTITHREADED) };
    if hr.is_ok() || hr == S_FALSE || hr == RPC_E_CHANGED_MODE {
        Ok(())
    } else {
        Err(hr.into())
    }
}

fn enumerate() -> windows::core::Result<Vec<(u32, f32, bool, ISimpleAudioVolume)>> {
    unsafe {
        ensure_com()?;
        let enumerator: IMMDeviceEnumerator =
            CoCreateInstance(&MMDeviceEnumerator, None, CLSCTX_ALL)?;
        let device = enumerator.GetDefaultAudioEndpoint(eRender, eMultimedia)?;
        let manager: IAudioSessionManager2 = device.Activate(CLSCTX_ALL, None)?;
        let sessions: IAudioSessionEnumerator = manager.GetSessionEnumerator()?;
        let count = sessions.GetCount()?;
        let mut out = Vec::new();
        for i in 0..count {
            let control = sessions.GetSession(i)?;
            let control2: IAudioSessionControl2 = control.cast()?;
            let pid = control2.GetProcessId()?;
            if pid == std::process::id() {
                continue;
            }
            let volume: ISimpleAudioVolume = control.cast()?;
            let master = volume.GetMasterVolume()?;
            let muted = volume.GetMute()?.as_bool();
            out.push((pid, master, muted, volume));
        }
        Ok(out)
    }
}

pub fn start(level: u32) -> windows::core::Result<()> {
    if ACTIVE.get() {
        return Ok(());
    }
    let sessions = enumerate()?;
    let mut saved = Vec::new();
    for (_pid, volume, muted, control) in sessions {
        unsafe {
            match level {
                0 => {
                    let _ = control.SetMute(true, std::ptr::null());
                }
                _ => {
                    let _ = control.SetMasterVolume(level as f32 / 100.0, std::ptr::null());
                }
            }
        }
        saved.push(Saved {
            volume,
            muted,
            control,
        });
    }
    SAVED.with(|s| s.replace(saved));
    ACTIVE.set(true);
    Ok(())
}

pub fn stop() {
    if !ACTIVE.get() {
        return;
    }
    SAVED.with(|s| {
        let saved = s.borrow();
        for item in saved.iter() {
            unsafe {
                let _ = item.control.SetMasterVolume(item.volume, std::ptr::null());
                let _ = item.control.SetMute(item.muted, std::ptr::null());
            }
        }
        drop(saved);
        s.replace(Vec::new());
    });
    ACTIVE.set(false);
}

pub fn recover() {
    stop();
}
