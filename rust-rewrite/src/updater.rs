//! Check GitHub Releases for a newer FreeDictate, download it, verify it, install it.
//!
//! Mirrors src/freedictate/updater.py.

use std::env;
use std::fs;
use std::io::{self, Read, Write, ErrorKind};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::{Mutex, LazyLock};
use std::time::Duration;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

use ureq::Agent;
use sha2::{Digest, Sha256};

// ------------------------------------------------------------------ config constants (from __init__.py)

pub const REPO: &str = "DavidHiFi/freedictate";
pub const VERSION: &str = "3.6.1";

const API: &str = "https://api.github.com/repos/{repo}/releases?per_page=15";

// ------------------------------------------------------------------ types

#[derive(Debug, Clone, PartialEq)]
pub struct Release {
    pub version: String,
    pub tag: String,
    pub name: String,
    pub notes: String,
    pub url: String,
    pub prerelease: bool,
    pub assets: std::collections::HashMap<String, String>, // name -> download URL
}

// ------------------------------------------------------------------ parsing and ranking

pub fn parse_version(v: &str) -> (i32, i32, i32, i32, i32) {
    let v = v.trim().to_lowercase();
    let v = v.strip_prefix('v').unwrap_or(&v);
    let mut parts = v.split(&['.', '-'][..]).peekable();
    let mut major = 0;
    let mut minor = 0;
    let mut patch = 0;
    // Each numeric slot takes the leading digits of its part, so "1_2_3"
    // reads as 1 the way Python's regex does, and a non-numeric part ends
    // the numeric section.
    for slot in [&mut major, &mut minor, &mut patch] {
        let digits: String = match parts.peek() {
            Some(p) => p.chars().take_while(|c| c.is_ascii_digit()).collect(),
            None => break,
        };
        if digits.is_empty() {
            break;
        }
        *slot = digits.parse().unwrap_or(0);
        parts.next();
    }
    // A final release sorts after its pre-releases, so it ranks 3;
    // alpha 0, beta 1, rc 2 (mirrors updater.py's _PREREL_RANK).
    let mut rank = 3;
    let mut prerelease_num = 0;
    if let Some(r) = parts.next() {
        // "rc1" style: the letters carry the rank, attached digits the
        // iteration; "beta.1" style leaves the number in the next part.
        let letters: String = r.chars().take_while(|c| !c.is_ascii_digit()).collect();
        let digits: String = r.chars().skip_while(|c| !c.is_ascii_digit()).collect();
        if !letters.is_empty() {
            rank = _PREREL_RANK.get(letters.as_str()).copied().unwrap_or(0);
            if !digits.is_empty() {
                prerelease_num = digits.parse().unwrap_or(0);
            } else if let Some(n) = parts.next() {
                prerelease_num = n.parse().unwrap_or(0);
            }
        }
    }
    (major, minor, patch, rank, prerelease_num)
}

static _PREREL_RANK: LazyLock<std::collections::HashMap<&str, i32>> =
    LazyLock::new(|| {
        [
            ("alpha", 0),
            ("a", 0),
            ("beta", 1),
            ("b", 1),
            ("pre", 1),
            ("preview", 1),
            ("rc", 2),
            ("c", 2),
        ]
        .iter()
        .cloned()
        .collect()
    });

pub fn newer(candidate: &str, current: &str) -> bool {
    parse_version(candidate) > parse_version(current)
}

// ------------------------------------------------------------------ HTTP helpers

fn _get(url: &str, timeout: i32) -> io::Result<ureq::http::Response<ureq::Body>> {
    let agent = Agent::new_with_config(
        Agent::config_builder().timeout_global(Some(Duration::from_secs(timeout as u64))).build()
    );
    let mut req = agent.get(url).header("User-Agent", &format!("FreeDictate/{}", VERSION));
    if url.contains("/repos/") {
        req = req.header("Accept", "application/vnd.github+json");
    }
    req.call().map_err(|e| io::Error::new(ErrorKind::Other, e))
}

// ------------------------------------------------------------------ release discovery

pub fn latest(include_prereleases: bool) -> Option<Release> {
    let api_url = API.replace("{repo}", REPO);
    let resp = _get(&api_url, 20);
    let mut resp = match resp {
        Ok(r) => r,
        Err(_) => return None,
    };
    let body: serde_json::Value = resp.body_mut().read_to_string().ok().and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok())?;
    let mut best: Option<Release> = None;
    if let Some(data) = body.as_array() {
        for rel in data {
            let draft = rel.get("draft").and_then(|v| v.as_bool()).unwrap_or(false);
            let prerelease = rel.get("prerelease").and_then(|v| v.as_bool()).unwrap_or(false);
            if draft || (prerelease && !include_prereleases) {
                continue;
            }
            let tag = rel.get("tag_name")?.as_str()?.to_string();
            let version = tag.trim_start_matches('v');
            let name = rel.get("name")?.as_str()?.to_string();
            let notes = rel.get("body")?.as_str()?.to_string();
            let html_url = rel.get("html_url")?.as_str()?.to_string();
            let mut assets = std::collections::HashMap::new();
            if let Some(assets_arr) = rel.get("assets")?.as_array() {
                for a in assets_arr {
                    let name = a.get("name")?.as_str()?.to_string();
                    let browser_download = a.get("browser_download_url")?.as_str()?.to_string();
                    assets.insert(name, browser_download);
                }
            }
            let cand = Release {
                version: version.to_string(),
                tag,
                name,
                notes,
                url: html_url,
                prerelease,
                assets,
            };
            if best.is_none() || parse_version(&cand.version) > parse_version(&best.as_ref().unwrap().version) {
                best = Some(cand);
            }
        }
    }
    best
}

pub fn check(include_prereleases: bool) -> Option<Release> {
    let rel = latest(include_prereleases);
    if let Some(ref r) = rel {
        if newer(&r.version, &VERSION) {
            return rel;
        }
    }
    None
}

// ------------------------------------------------------------------ asset selection

pub fn _asset(rel: &Release, portable: bool) -> io::Result<(String, String)> {
    for (name, url) in &rel.assets {
        let n = name.to_ascii_lowercase();
        if portable && n.ends_with(".zip") && n.contains("portable") {
            return Ok((name.clone(), url.clone()));
        }
        if !portable && n.ends_with(".exe") && n.contains("setup") {
            return Ok((name.clone(), url.clone()));
        }
    }
    Err(io::Error::new(ErrorKind::NotFound, "This release has no download for your kind of install."))
}

pub fn _expected_sha(rel: &Release, name: &str) -> Option<String> {
    // The checksum asset may be "SHA256SUMS" or carry an extension after it.
    let sha_url = rel
        .assets
        .iter()
        .find(|(k, _)| k.to_uppercase().starts_with("SHA256SUMS"))
        .map(|(_, u)| u)?;
    let resp = _get(sha_url, 20);
    let mut resp = match resp {
        Ok(r) => r,
        Err(_) => return None,
    };
    let body = resp.body_mut().read_to_string().ok()?;
    for line in body.lines() {
        let parts: Vec<&str> = line.split_whitespace().collect();
        // The name may be written in binary mode ("*name") or plain; leading
        // asterisks are ignored either way, as in updater.py.
        if parts.len() == 2 && parts[1].trim_start_matches('*') == name {
            return Some(parts[0].to_lowercase());
        }
    }
    None
}

// ------------------------------------------------------------------ download

pub fn download(rel: &Release, progress: Option<&dyn Fn(u64, u64)>, cancel: Option<&Mutex<bool>>) -> io::Result<PathBuf> {
    let (name, url) = _asset(rel, portable())?;
    let want = _expected_sha(rel, &name).ok_or_else(|| io::Error::new(ErrorKind::NotFound, "This release has no checksum for the download, so it wasn't fetched."))?;
    let tmp = PathBuf::from("FreeDictate-update").join(&name);
    if let Some(p) = tmp.parent() {
        fs::create_dir_all(p)?;
    }
    let mut file = fs::File::create(&tmp)?;
    let mut sha = Sha256::new();
    let mut done = 0u64;
    let agent = Agent::new_with_config(
        Agent::config_builder().timeout_global(Some(Duration::from_secs(60))).build()
    );
    let resp = agent.get(&url).call().map_err(|e| io::Error::new(ErrorKind::Other, e))?;
    let total = resp
        .headers()
        .get("Content-Length")
        .and_then(|v| v.to_str().ok().and_then(|s| s.parse::<u64>().ok()))
        .unwrap_or(0);
    let mut reader = resp.into_body().into_reader();
    let mut buf = [0u8; 1 << 18];
    loop {
        if let Some(c) = cancel {
            if *c.lock().unwrap() { return Err(io::Error::new(ErrorKind::Interrupted, "Download cancelled")); }
        }
        let n = reader.read(&mut buf)?;
        if n == 0 { break; }
        file.write_all(&buf[..n])?;
        sha.update(&buf[..n]);
        done += n as u64;
        if let Some(p) = progress {
            p(done, total);
        }
    }
    let final_hex = format!("{:x}", sha.finalize());
    if final_hex != want {
        let _ = fs::remove_file(&tmp);
        return Err(io::Error::new(ErrorKind::InvalidData, "The download didn't match its checksum, so it wasn't installed. Try again."));
    }
    Ok(tmp)
}

// ------------------------------------------------------------------ install

fn portable() -> bool {
    // Check for portable flag (--portable) or presence of portable.txt in workspace root.
    // This is a best-effort port; the Rust build may not yet support portable mode.
    if env::args().any(|a| a == "--portable") {
        return true;
    }
    let marker = PathBuf::from(".portable.txt");
    if marker.exists() { return true; }
    false
}

pub fn install(file: PathBuf) -> io::Result<()> {
    if file.extension().map_or(false, |e| e.to_ascii_lowercase() == "exe") {
        // Installer exe with silent flags (replicates Python's --silent, --suppressmsgboxes, etc.)
        Command::new(file)
            .args(["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/UPDATE=1"])
            .creation_flags(0x08000000) // CREATE_NO_WINDOW
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|e| io::Error::new(ErrorKind::Other, e))?;
        return Ok(());
    }
    // Portable: write a PowerShell script like Python does.
    // PowerShell script written to TEMP/FreeDictate-update/apply-portable.ps1
    let app = env::var("APPDATA")
        .map(|appdata| PathBuf::from(appdata).join("FreeDictate-Rust"))
        .unwrap_or_else(|_| PathBuf::from("."));
    let exe = app.join("FreeDictate.exe");
    // Simple script: expand archive, copy files (skip 'data' and 'portable.txt'), restart.
    let script = format!(
        "$ErrorActionPreference = 'Stop';\n$stage = Join-Path $env:TEMP 'FreeDictate-update\\stage';\nRemove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue;\nExpand-Archive -LiteralPath '{}' -DestinationPath $stage -Force;\n$src = Get-ChildItem $stage -Directory | Select-Object -First 1;\nif (-not (Test-Path (Join-Path $src.FullName 'FreeDictate.exe'))) {{ $src = Get-Item $stage; }}\nGet-ChildItem $src.FullName | Where-Object {{ $_.Name -notin @('data', 'portable.txt') }} | ForEach-Object {{ Copy-Item $_.FullName -Destination '{}' -Recurse -Force; }}\nif (-not (Get-Process -Name FreeDictate -ErrorAction SilentlyContinue)) {{ Start-Process -FilePath '{}' }};",
        file.display(), app.display(), exe.display()
    );
    let temp_dir = env::var("TEMP").unwrap_or_else(|_| "C:\\Temp".to_string());
    let script_dir = PathBuf::from(temp_dir).join("FreeDictate-update");
    fs::create_dir_all(&script_dir)?;
    let script_path = script_dir.join("apply-portable.ps1");
    fs::write(&script_path, script)?;
    Command::new("powershell")
        .args([
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-File",
            script_path.to_str().ok_or_else(|| io::Error::new(ErrorKind::InvalidData, "script path invalid"))?,
        ])
        .creation_flags(0x08000000)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| io::Error::new(ErrorKind::Other, e))?;
    Ok(())
}
