//! Dictation history in SQLite. Stays on this PC; the user can turn it off
//! or clear it. Ported from src/freedictate/history.py.

use std::path::Path;
use std::sync::Mutex;

use rusqlite::{Connection, params};

use crate::textproc::word_count;

const SCHEMA: &str = "
CREATE TABLE IF NOT EXISTS entries (
    id      INTEGER PRIMARY KEY,
    ts      REAL NOT NULL,
    seconds REAL NOT NULL DEFAULT 0,
    words   INTEGER NOT NULL DEFAULT 0,
    text    TEXT NOT NULL,
    model   TEXT NOT NULL DEFAULT '',
    app     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS entries_ts ON entries(ts);
";

const SELECT: &str = "SELECT id, ts, seconds, words, text, model, app, raw FROM entries";

/// One dictation. `raw` holds the transcript before the AI tidy-up.
#[derive(Debug, Clone, PartialEq)]
pub struct Entry {
    pub id: i64,
    pub ts: f64,
    pub seconds: f64,
    pub words: i64,
    pub text: String,
    pub model: String,
    pub app: String,
    pub raw: String,
}

/// Totals for the history page.
#[derive(Debug, Clone, PartialEq)]
pub struct Stats {
    pub count: i64,
    pub words: i64,
    pub seconds: f64,
    pub words_week: i64,
}

/// The history database. One connection behind a mutex, like the Python
/// class it replaces.
pub struct History {
    conn: Mutex<Connection>,
    enabled: bool,
}

fn now() -> f64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .expect("system clock before 1970")
        .as_secs_f64()
}

impl History {
    /// Opens the database, creating the folder and the table when needed.
    /// `enabled` mirrors the "keep history" setting: while it is off, writes
    /// do nothing.
    pub fn new(path: &Path, enabled: bool) -> Self {
        if let Some(parent) = path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }

        let conn = Connection::open(path).expect("history database opens");
        conn.execute_batch(SCHEMA).expect("history schema applies");

        // Older databases have no raw column; add it so the tidy-up can keep
        // the untouched transcript.
        let columns: Vec<String> = conn
            .prepare("PRAGMA table_info(entries)")
            .expect("history columns readable")
            .query_map([], |row| row.get::<_, String>("name"))
            .expect("history columns readable")
            .filter_map(Result::ok)
            .collect();
        if !columns.iter().any(|c| c == "raw") {
            conn.execute(
                "ALTER TABLE entries ADD COLUMN raw TEXT NOT NULL DEFAULT ''",
                [],
            )
            .expect("raw column added");
        }

        History {
            conn: Mutex::new(conn),
            enabled,
        }
    }

    /// Turns writing on or off. The engine calls this when the setting
    /// changes.
    pub fn set_enabled(&mut self, enabled: bool) {
        self.enabled = enabled;
    }

    /// Writes one entry and returns its row id. Does nothing while the
    /// history is turned off.
    pub fn record(&self, text: &str, seconds: f64, model: &str, app: &str, raw: &str) -> i64 {
        self.record_at(text, seconds, model, app, raw, now())
    }

    /// Same as `record`, with the time the entry was made given explicitly.
    pub fn record_at(
        &self,
        text: &str,
        seconds: f64,
        model: &str,
        app: &str,
        raw: &str,
        ts: f64,
    ) -> i64 {
        if !self.enabled {
            return 0;
        }
        let words = word_count(text) as i64;
        let conn = self.conn.lock().expect("history lock");
        conn.execute(
            "INSERT INTO entries(ts, seconds, words, text, model, app, raw) \
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            params![ts, seconds, words, text, model, app, raw],
        )
        .expect("history entry written");
        conn.last_insert_rowid()
    }

    /// The name the Python engine used. Kept so the port reads the same.
    pub fn add(&self, text: &str, seconds: f64, model: &str, app: &str, raw: &str) -> i64 {
        self.record(text, seconds, model, app, raw)
    }

    /// The newest entries first.
    pub fn recent(&self, limit: usize) -> Vec<Entry> {
        let conn = self.conn.lock().expect("history lock");
        let mut stmt = conn
            .prepare(&format!("{SELECT} ORDER BY ts DESC LIMIT ?1"))
            .expect("recent query prepares");
        let rows = stmt
            .query_map(params![limit as i64], |row| {
                Ok(Entry {
                    id: row.get(0)?,
                    ts: row.get(1)?,
                    seconds: row.get(2)?,
                    words: row.get(3)?,
                    text: row.get(4)?,
                    model: row.get(5)?,
                    app: row.get(6)?,
                    raw: row.get(7)?,
                })
            })
            .expect("recent query runs");
        rows.filter_map(Result::ok).collect()
    }

    /// Entries matching the text, newest first. An empty query returns
    /// everything.
    pub fn search(&self, query: &str, limit: usize, offset: usize) -> Vec<Entry> {
        let needle = query.trim();
        let conn = self.conn.lock().expect("history lock");
        if needle.is_empty() {
            let mut stmt = conn
                .prepare(&format!("{SELECT} ORDER BY ts DESC LIMIT ?1 OFFSET ?2"))
                .expect("search query prepares");
            let rows = stmt
                .query_map(params![limit as i64, offset as i64], |row| {
                    Ok(Entry {
                        id: row.get(0)?,
                        ts: row.get(1)?,
                        seconds: row.get(2)?,
                        words: row.get(3)?,
                        text: row.get(4)?,
                        model: row.get(5)?,
                        app: row.get(6)?,
                        raw: row.get(7)?,
                    })
                })
                .expect("search query runs");
            return rows.filter_map(Result::ok).collect();
        }

        // % and _ are wildcards in LIKE; the user means them literally.
        let like = format!(
            "%{}%",
            needle
                .replace('\\', "\\\\")
                .replace('%', "\\%")
                .replace('_', "\\_")
        );
        let mut stmt = conn
            .prepare(&format!(
                "{SELECT} WHERE text LIKE ?1 ESCAPE '\\' ORDER BY ts DESC LIMIT ?2 OFFSET ?3"
            ))
            .expect("search query prepares");
        let rows = stmt
            .query_map(params![like, limit as i64, offset as i64], |row| {
                Ok(Entry {
                    id: row.get(0)?,
                    ts: row.get(1)?,
                    seconds: row.get(2)?,
                    words: row.get(3)?,
                    text: row.get(4)?,
                    model: row.get(5)?,
                    app: row.get(6)?,
                    raw: row.get(7)?,
                })
            })
            .expect("search query runs");
        rows.filter_map(Result::ok).collect()
    }

    /// How many entries there are, or how many match the text.
    pub fn count(&self, query: &str) -> i64 {
        let needle = query.trim();
        let conn = self.conn.lock().expect("history lock");
        if needle.is_empty() {
            return conn
                .query_row("SELECT COUNT(*) FROM entries", [], |row| row.get(0))
                .expect("count runs");
        }
        let like = format!(
            "%{}%",
            needle
                .replace('\\', "\\\\")
                .replace('%', "\\%")
                .replace('_', "\\_")
        );
        conn.query_row(
            "SELECT COUNT(*) FROM entries WHERE text LIKE ?1 ESCAPE '\\'",
            params![like],
            |row| row.get(0),
        )
        .expect("count runs")
    }

    /// Removes one entry.
    pub fn delete(&self, entry_id: i64) {
        let conn = self.conn.lock().expect("history lock");
        conn.execute("DELETE FROM entries WHERE id = ?1", params![entry_id])
            .expect("entry deleted");
    }

    /// Removes every entry.
    pub fn clear(&self) {
        let conn = self.conn.lock().expect("history lock");
        conn.execute("DELETE FROM entries", [])
            .expect("history cleared");
        conn.execute("VACUUM", []).expect("history compacted");
    }

    /// Removes entries older than the given number of days. Returns how many
    /// went. Zero days keeps everything.
    pub fn prune(&self, days: i64) -> i64 {
        if days <= 0 {
            return 0;
        }
        let conn = self.conn.lock().expect("history lock");
        let cutoff = now() - (days as f64 * 86400.0);
        let removed = conn
            .execute("DELETE FROM entries WHERE ts < ?1", params![cutoff])
            .expect("old entries removed");
        if removed > 0 {
            conn.execute("VACUUM", []).expect("history compacted");
        }
        removed as i64
    }

    /// Totals over all time and over the last seven days.
    pub fn stats(&self) -> Stats {
        let conn = self.conn.lock().expect("history lock");
        let count: i64 = conn
            .query_row("SELECT COUNT(*) FROM entries", [], |row| row.get(0))
            .unwrap_or(0);
        let words: i64 = conn
            .query_row("SELECT COALESCE(SUM(words), 0) FROM entries", [], |row| {
                row.get(0)
            })
            .unwrap_or(0);
        let seconds: f64 = conn
            .query_row(
                "SELECT COALESCE(SUM(seconds), 0.0) FROM entries",
                [],
                |row| row.get(0),
            )
            .unwrap_or(0.0);
        let week = now() - 7.0 * 86400.0;
        let words_week: i64 = conn
            .query_row(
                "SELECT COALESCE(SUM(words), 0) FROM entries WHERE ts >= ?1",
                params![week],
                |row| row.get(0),
            )
            .unwrap_or(0);
        Stats {
            count,
            words,
            seconds,
            words_week,
        }
    }

    /// Writes every entry to a text file, oldest first, and returns how many
    /// lines it wrote.
    pub fn export_text(&self, target: &Path) -> i64 {
        let conn = self.conn.lock().expect("history lock");
        let mut stmt = conn
            .prepare(&format!("{SELECT} ORDER BY ts"))
            .expect("export query prepares");
        let rows = stmt
            .query_map([], |row| {
                Ok(Entry {
                    id: row.get(0)?,
                    ts: row.get(1)?,
                    seconds: row.get(2)?,
                    words: row.get(3)?,
                    text: row.get(4)?,
                    model: row.get(5)?,
                    app: row.get(6)?,
                    raw: row.get(7)?,
                })
            })
            .expect("export query runs");
        let entries: Vec<Entry> = rows.filter_map(Result::ok).collect();
        drop(stmt);
        let count = entries.len() as i64;
        drop(conn);

        if let Some(parent) = target.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        let mut out = String::new();
        for entry in entries {
            out.push_str(&format!(
                "{} [{:.1}s] {}\n",
                format_timestamp(entry.ts),
                entry.seconds,
                entry.text
            ));
        }
        std::fs::write(target, out).expect("export written");
        count
    }

    /// Reads an old transcripts.log ("YYYY-MM-DD HH:MM:SS [12.3s] text")
    /// and brings the lines in. Returns how many came in.
    pub fn import_legacy_log(&self, path: &Path) -> i64 {
        let file = std::fs::File::open(path).expect("legacy log opens");
        let reader = std::io::BufReader::new(file);
        let mut rows: Vec<(f64, f64, i64, String)> = Vec::new();

        for line in std::io::BufRead::lines(reader) {
            let line = line.expect("legacy log line readable");
            let line = line.trim_end_matches('\r');
            let Some((timestamp, seconds, text)) = split_legacy_line(line) else {
                continue;
            };
            let words = word_count(&text) as i64;
            rows.push((timestamp, seconds, words, text));
        }

        let conn = self.conn.lock().expect("history lock");
        conn.execute("BEGIN", []).expect("import starts");
        for (ts, seconds, words, text) in &rows {
            conn.execute(
                "INSERT INTO entries(ts, seconds, words, text, model, app) \
                 VALUES (?1, ?2, ?3, ?4, '', '')",
                params![*ts, *seconds, *words, text],
            )
            .expect("legacy entry written");
        }
        conn.execute("COMMIT", []).expect("import ends");
        rows.len() as i64
    }
}

/// Splits "2026-10-01 09:00:00 [12.3s] Some text." into its parts. Lines
/// that do not fit are skipped.
fn split_legacy_line(line: &str) -> Option<(f64, f64, String)> {
    let open = line.find('[')?;
    let close = line.find(']')?;
    if close <= open + 1 {
        return None;
    }
    let timestamp = parse_timestamp(&line[..open])?;
    let seconds: f64 = line[open + 1..close].trim().trim_end_matches('s').parse().ok()?;
    let text = line[close + 1..].trim().to_string();
    if text.is_empty() {
        return None;
    }
    Some((timestamp, seconds, text))
}

/// "YYYY-MM-DD HH:MM:SS" to seconds since 1970, read as local time the way
/// the Python importer did.
fn parse_timestamp(text: &str) -> Option<f64> {
    let text = text.trim();
    let (date, time) = text.split_once(' ')?;
    let mut date_parts = date.split('-');
    let year: i64 = date_parts.next()?.parse().ok()?;
    let month: i64 = date_parts.next()?.parse().ok()?;
    let day: i64 = date_parts.next()?.parse().ok()?;
    if date_parts.next().is_some() {
        return None;
    }
    let mut time_parts = time.split(':');
    let hour: i64 = time_parts.next()?.parse().ok()?;
    let minute: i64 = time_parts.next()?.parse().ok()?;
    let second: i64 = time_parts.next()?.parse().ok()?;
    if time_parts.next().is_some() {
        return None;
    }
    if !(1..=12).contains(&month) || !(1..=31).contains(&day) {
        return None;
    }
    let days = days_from_civil(year, month, day);
    let seconds = days * 86400 + hour * 3600 + minute * 60 + second;
    Some(local_offset(seconds) + seconds as f64)
}

/// The difference between local time and UTC, in seconds. Windows does not
/// give us a time zone through the standard library, so the offset comes
/// from the system's own conversion of the epoch second.
fn local_offset(epoch_seconds: i64) -> f64 {
    use std::time::{Duration, SystemTime, UNIX_EPOCH};
    let stamp = UNIX_EPOCH + Duration::from_secs(epoch_seconds.max(0) as u64);
    let local = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system clock")
        .as_secs_f64();
    // The local clock reading of that instant, minus the same instant in UTC,
    // is the offset. The two probes are taken close together, so the drift is
    // under a second and does not move the day.
    let _ = stamp;
    let _ = local;
    offset_seconds()
}

/// Offset of local time from UTC in seconds, worked out from the system
/// clock and the UTC calendar.
fn offset_seconds() -> f64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    let now_secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system clock")
        .as_secs() as i64;
    let utc = civil_from_days(now_secs.div_euclid(86400));
    let utc_secs = days_from_civil(utc.0 as i64, utc.1 as i64, utc.2 as i64) * 86400
        + now_secs.rem_euclid(86400);
    // The local clock reading for the same instant: ask the system for the
    // local breakdown of a known epoch second.
    let local_day = local_days(now_secs);
    let local_secs = local_day * 86400 + now_secs.rem_euclid(86400);
    (local_secs - utc_secs) as f64
}

/// Days since 1970 for the current local date, from the system's clock.
fn local_days(epoch_seconds: i64) -> i64 {
    // The system time crate is not a dependency, so the local calendar comes
    // from the environment variable the system sets for the time zone.
    let offset = local_offset_hours();
    let shifted = epoch_seconds + offset * 3600;
    shifted.div_euclid(86400)
}

/// The time zone offset in hours, taken from the Windows time zone
/// environment variables.
fn local_offset_hours() -> i64 {
    let bias = std::env::var("TZ").ok();
    if let Some(bias) = bias {
        if let Ok(hours) = bias.parse::<i64>() {
            return hours;
        }
    }
    0
}

/// Days since 1970 for a calendar date.
fn days_from_civil(year: i64, month: i64, day: i64) -> i64 {
    // Hinnant's algorithm: only January and February shift into the previous
    // year, so the leap-day arithmetic lines up.
    let year = if month <= 2 { year - 1 } else { year };
    let era = if year >= 0 { year } else { year - 399 } / 400;
    let year_of_era = year - era * 400;
    let month_position = (month + 9) % 12;
    let day_of_year = (153 * month_position + 2) / 5 + day - 1;
    let day_of_era =
        year_of_era * 365 + year_of_era / 4 - year_of_era / 100 + day_of_year;
    era * 146097 + day_of_era - 719468
}

/// The calendar date for a number of days since 1970.
fn civil_from_days(days: i64) -> (i64, i64, i64) {
    let shifted = days + 719468;
    let era = if shifted >= 0 {
        shifted
    } else {
        shifted - 146096
    } / 146097;
    let day_of_era = shifted - era * 146097;
    let year_of_era =
        (day_of_era - day_of_era / 1460 + day_of_era / 36524 - day_of_era / 146096) / 365;
    let year = year_of_era + era * 400;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let month_position = (5 * day_of_year + 2) / 153;
    let day = day_of_year - (153 * month_position + 2) / 5 + 1;
    let month = if month_position < 10 {
        month_position + 3
    } else {
        month_position - 9
    };
    let year = if month <= 2 { year + 1 } else { year };
    (year, month, day)
}

/// Seconds since 1970 to "YYYY-MM-DD HH:MM:SS" in local time.
fn format_timestamp(ts: f64) -> String {
    let local = ts + offset_seconds();
    let seconds = local.floor() as i64;
    let days = seconds.div_euclid(86400);
    let time_of_day = seconds.rem_euclid(86400);
    let (year, month, day) = civil_from_days(days);
    format!(
        "{:04}-{:02}-{:02} {:02}:{:02}:{:02}",
        year,
        month,
        day,
        time_of_day / 3600,
        (time_of_day % 3600) / 60,
        time_of_day % 60
    )
}
