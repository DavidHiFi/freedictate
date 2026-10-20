//! Turn Whisper's raw text into what gets pasted. Ported from
//! src/freedictate/textproc.py; fancy-regex carries the look-behinds the
//! Python patterns rely on.

use std::sync::LazyLock;

use fancy_regex::{Captures, NoExpand, Regex};

// Hesitation sounds only. Words like "like" or "you know" carry meaning often
// enough that removing them would change what was said.
const FILLER_CORE: &str = r"u+h+|e+r+m*|a+h+|h+m+|m+h*m+";
// "um" on its own: a real word in Portuguese and German, so it is only
// filtered for other languages.
const FILLER_UM: &str = r"u+m+";
const FILLER_TAIL: &str = r"(?![\w'])[,.]?\s*";

static FILLER: LazyLock<Regex> = LazyLock::new(|| {
    re(&format!(r"(?i)(?<![\w'])(?:{FILLER_UM}|{FILLER_CORE}){FILLER_TAIL}"))
});
static FILLER_STRICT: LazyLock<Regex> =
    LazyLock::new(|| re(&format!(r"(?i)(?<![\w'])(?:{FILLER_CORE}){FILLER_TAIL}")));

// Private marks used while the text is being rebuilt; none survive clean().
const CAP: char = '\x01'; // the next letter starts a sentence
const NOSPACE_R: char = '\x04'; // drop the spaces that follow
const NOSPACE_L: char = '\x05'; // drop the spaces that come before

// Spoken commands: (phrase, symbol, how it joins its neighbours).
//   attach  sticks to the word before, one space after      ,  .  ?
//   open    one space before, none after                    (  "
//   close   none before, one space after                    )  "
//   join    no space on either side                         -  _
//   word    stands alone with a space each side             *  -
//   line    starts a new line or list item
const SPOKEN: &[(&str, &str, &str)] = &[
    (r"new paragraph", "\n\n\x01", "line"),
    (r"new line", "\n\x01", "line"),
    (r"(?:dot|bullet) point", "\n- \x01", "line"),
    (r"full stop", ".\x01", "attach"),
    (r"question mark", "?\x01", "attach"),
    (r"exclamation (?:mark|point)", "!\x01", "attach"),
    (r"comma", ",", "attach"),
    (r"semi[- ]?colon", ";", "attach"),
    (r"colon", ":", "attach"),
    (r"open (?:bracket|paren(?:thesis)?)", "(", "open"),
    (r"close (?:bracket|paren(?:thesis)?)", ")", "close"),
    (r"open quote", "\"", "open"),
    (r"(?:close|end) quote", "\"", "close"),
    (r"hyphen", "-", "join"),
    (r"underscore", "_", "join"),
    (r"asterisk", "*", "word"),
    (r"dash", "-", "word"),
];
const PUNCT: &str = r"[,.;:!?]?";

fn joins(kind: &str) -> (String, String) {
    match kind {
        "attach" | "close" => (NOSPACE_L.to_string(), " ".into()),
        "open" => (" ".into(), NOSPACE_R.to_string()),
        "join" => (NOSPACE_L.to_string(), NOSPACE_R.to_string()),
        "word" => (" ".into(), " ".into()),
        _ => (String::new(), String::new()),
    }
}

// A line break keeps the punctuation the speaker put before it ("Dear John,
// new line"); a spoken mark replaces whatever Whisper guessed there.
static SPOKEN_RE: LazyLock<Vec<(Regex, String)>> = LazyLock::new(|| {
    SPOKEN
        .iter()
        .map(|(phrase, rep, kind)| {
            let before = if *kind == "line" {
                String::new()
            } else {
                format!(r"{PUNCT}[ \t]*")
            };
            let pattern = format!(r"(?i)[ \t]*{before}\b(?:{phrase})\b{PUNCT}[ \t]*");
            let (left, right) = joins(kind);
            (re(&pattern), format!("{left}{rep}{right}"))
        })
        .collect()
});
// "literal comma" types the word itself.
static LITERAL: LazyLock<Regex> = LazyLock::new(|| {
    let phrases: Vec<&str> = SPOKEN.iter().map(|(p, _, _)| *p).collect();
    re(&format!(r"(?i)\bliteral[,.]?\s+({})\b", phrases.join("|")))
});

// Words people repeat on purpose, or that are correct twice in a row ("they
// had had enough", "what it is is").
const REPEAT_OK: &[&str] = &[
    "had", "that", "is", "do", "really", "very", "so", "much", "many", "way", "far", "long", "more",
    "again", "over", "round", "on", "no", "yes", "yeah", "ha", "haha", "bye", "night", "please",
    "there", "blah", "knock", "tick", "chop", "go", "hey", "hi", "oh", "wow", "woo", "yay", "now",
    "well", "ok", "okay", "boom", "bang", "super", "little", "tiny", "big",
];

fn re(pattern: &str) -> Regex {
    Regex::new(pattern).expect("textproc pattern compiles")
}

fn sub(pattern: &Regex, text: &str, rep: &str) -> String {
    pattern.replace_all(text, rep).into_owned()
}

fn sub_literal(pattern: &Regex, text: &str, rep: &str) -> String {
    pattern.replace_all(text, NoExpand(rep)).into_owned()
}

fn base_lang(language: Option<&str>) -> String {
    let lang = language.unwrap_or("");
    let lang = lang.split('-').next().unwrap_or("");
    lang.split('_').next().unwrap_or("").to_lowercase()
}

fn norm(token: &str) -> String {
    token
        .chars()
        .filter(|c| c.is_alphanumeric() || *c == '_' || *c == '\'')
        .collect::<String>()
        .to_lowercase()
}

fn upper_first(word: &str) -> String {
    let mut chars = word.chars();
    match chars.next() {
        Some(first) => first.to_uppercase().chain(chars).collect(),
        None => String::new(),
    }
}

/// Collapse a word or phrase said twice in a row ("the the", "I want, I want
/// to"). The second copy stays because it carries the punctuation that leads
/// into the rest of the sentence. Never reaches across a sentence end or a
/// line break.
pub fn remove_repeats(text: &str) -> String {
    let mut out_lines = Vec::new();
    for line in text.split('\n') {
        let mut tokens: Vec<String> = line.split(' ').map(str::to_string).collect();
        let mut i = 0;
        while i < tokens.len() {
            let normed: Vec<String> = tokens.iter().map(|t| norm(t)).collect();
            let mut removed = false;
            for n in (1..=6.min((tokens.len() - i) / 2)).rev() {
                let a = &normed[i..i + n];
                let b = &normed[i + n..i + 2 * n];
                if a != b || a.iter().any(String::is_empty) {
                    continue;
                }
                if n == 1
                    && (REPEAT_OK.contains(&a[0].as_str())
                        || a[0].chars().all(|c| c.is_numeric()))
                {
                    continue;
                }
                if tokens[i + n - 1].ends_with(['.', '!', '?']) {
                    continue;
                }
                let first_upper = tokens[i].chars().next().is_some_and(char::is_uppercase);
                let second_lower = tokens[i + n].chars().next().is_some_and(char::is_lowercase);
                if first_upper && second_lower {
                    tokens[i + n] = upper_first(&tokens[i + n]);
                }
                tokens.drain(i..i + n);
                removed = true;
                break;
            }
            if !removed {
                i += 1;
            }
        }
        out_lines.push(tokens.join(" "));
    }
    out_lines.join("\n")
}

static NOSPACE_L_RE: LazyLock<Regex> = LazyLock::new(|| re("[ \t]*\x05"));
static NOSPACE_R_RE: LazyLock<Regex> = LazyLock::new(|| re("\x04[ \t]*"));
static LINE_SPACES: LazyLock<Regex> = LazyLock::new(|| re(r"[ \t]*\n[ \t]*"));
static LINE_THEN_ITEM: LazyLock<Regex> = LazyLock::new(|| re("\n\x01?\n- "));
static EMPTY_ITEM: LazyLock<Regex> = LazyLock::new(|| re("\n- \x01?(?=\n|$)"));
static SHIELDED: LazyLock<Regex> = LazyLock::new(|| re(r"\x03(\d+)\x03"));

fn spoken(text: &str) -> String {
    let mut kept: Vec<String> = Vec::new();
    let mut text = LITERAL
        .replace_all(text, |caps: &Captures<'_, str>| {
            kept.push(caps[1].to_string());
            format!("\x03{}\x03", kept.len() - 1)
        })
        .into_owned();
    for (pattern, rep) in SPOKEN_RE.iter() {
        text = sub_literal(pattern, &text, rep);
    }
    text = sub(&NOSPACE_L_RE, &text, "");
    text = sub(&NOSPACE_R_RE, &text, "");
    text = sub(&LINE_SPACES, &text, "\n");
    text = sub(&LINE_THEN_ITEM, &text, "\n- "); // "new line, dot point"
    text = sub(&EMPTY_ITEM, &text, "\n"); // an empty list item
    SHIELDED
        .replace_all(&text, |caps: &Captures<'_, str>| {
            let index: usize = caps[1].parse().unwrap_or(usize::MAX);
            kept.get(index).cloned().unwrap_or_default()
        })
        .into_owned()
}

/// One user find/replace pair, matched as a whole word in any case.
#[derive(Debug, Clone, Default)]
pub struct Replacement {
    pub find: String,
    pub replace: String,
}

/// The saved "replacements" config list [{"find": str, "replace": str}]
/// parsed for clean(). Mirrors Python: entries that are not objects, that
/// miss "find", or whose find is blank after trimming are skipped;
/// "replace" missing strings as empty.
pub fn replacements_from_config(value: Option<&serde_json::Value>) -> Vec<Replacement> {
    let mut out = Vec::new();
    let Some(entries) = value.and_then(|v| v.as_array()) else {
        return out;
    };
    for entry in entries {
        let Some(object) = entry.as_object() else {
            continue;
        };
        let Some(find) = object.get("find").and_then(|f| f.as_str()) else {
            continue;
        };
        let find = find.trim().to_string();
        if find.is_empty() {
            continue;
        }
        let replace = object
            .get("replace")
            .and_then(|r| r.as_str())
            .unwrap_or("")
            .to_string();
        out.push(Replacement { find, replace });
    }
    out
}

pub fn apply_replacements(text: &str, replacements: &[Replacement]) -> String {
    let mut text = text.to_string();
    for r in replacements {
        let find = r.find.trim();
        if find.is_empty() {
            continue;
        }
        let pattern = re(&format!(r"(?i)(?<!\w){}(?!\w)", fancy_regex::escape(find)));
        text = sub_literal(&pattern, &text, &r.replace);
    }
    text
}

static CAP_LINES: LazyLock<Regex> = LazyLock::new(|| re(r"(^|\n)((?:[-*] |\d+\. )?\s*[a-z])"));

/// Capitalize the first letter of the text and of each line or list item.
fn cap_lines(text: &str) -> String {
    CAP_LINES
        .replace_all(text, |caps: &Captures<'_, str>| {
            format!("{}{}", &caps[1], caps[2].to_uppercase())
        })
        .into_owned()
}

static SPACE_BEFORE_CLOSE: LazyLock<Regex> = LazyLock::new(|| re(r"[ \t]+([.,!?;:)\]}])"));
static SPACE_AFTER_OPEN: LazyLock<Regex> = LazyLock::new(|| re(r"([({\[])[ \t]+"));

/// No space before a closing mark, none after an opening one. Only runs of
/// spaces and tabs are touched, so voice-command newlines survive.
fn tidy_punct(text: &str) -> String {
    let text = sub(&SPACE_BEFORE_CLOSE, text, "${1}");
    sub(&SPACE_AFTER_OPEN, &text, "${1}")
}

/// The switches that shape clean(); defaults match the Python keyword args.
#[derive(Debug, Clone)]
pub struct Options {
    pub remove_fillers: bool,
    pub voice_commands: bool,
    pub capitalize: bool,
    pub end_punctuation: bool,
    pub repeats: bool,
    pub replacements: Vec<Replacement>,
    pub language: Option<String>,
}

impl Default for Options {
    fn default() -> Self {
        Options {
            remove_fillers: true,
            voice_commands: true,
            capitalize: true,
            end_punctuation: true,
            repeats: false,
            replacements: Vec::new(),
            language: None,
        }
    }
}

static SPACE_BEFORE_MARK: LazyLock<Regex> = LazyLock::new(|| re(r"\s+([,.!?])"));
static DOUBLE_CONNECTOR: LazyLock<Regex> = LazyLock::new(|| re(r"([,;:])(\s*[,;:])+"));
static CONNECTOR_BEFORE_END: LazyLock<Regex> = LazyLock::new(|| re(r"([,;:]+)(\s*[.!?])"));
static LEADING_CONNECTOR: LazyLock<Regex> = LazyLock::new(|| re(r"^[,.;:\s]+"));
static CAP_MARK: LazyLock<Regex> = LazyLock::new(|| re("\x01([\\s\"(]*)([a-z])"));
static SPACE_RUNS: LazyLock<Regex> = LazyLock::new(|| re(r"[ \t]+"));
static LIST_LINE: LazyLock<Regex> = LazyLock::new(|| re(r"^(?:[-*] |\d+\. )"));

pub fn clean(raw: &str, opts: &Options) -> String {
    let mut text = raw.split_whitespace().collect::<Vec<_>>().join(" ");
    if text.is_empty() {
        return String::new();
    }
    if opts.remove_fillers {
        let keep_um = matches!(base_lang(opts.language.as_deref()).as_str(), "pt" | "de");
        let filler = if keep_um { &*FILLER_STRICT } else { &*FILLER };
        text = sub(filler, &text, "");
        text = sub(&SPACE_BEFORE_MARK, &text, "${1}");
        // Removing a filler can leave a connector pointing at nothing.
        text = sub(&DOUBLE_CONNECTOR, &text, "${1}");
        text = sub(&CONNECTOR_BEFORE_END, &text, "${2}");
        text = text.trim_end_matches([' ', ',', ';', ':']).to_string();
        text = sub(&LEADING_CONNECTOR, &text, "");
    }
    if opts.repeats {
        text = remove_repeats(&text);
    }
    text = apply_replacements(&text, &opts.replacements);
    if opts.voice_commands {
        text = spoken(&text);
        text = tidy_punct(&text);
    }
    // Replacements run again after spoken punctuation, so a find that only
    // becomes matchable once "dash" is " - " still wins.
    text = apply_replacements(&text, &opts.replacements);
    if opts.capitalize {
        text = CAP_MARK
            .replace_all(&text, |caps: &Captures<'_, str>| {
                format!("{}{}", &caps[1], caps[2].to_uppercase())
            })
            .into_owned();
    }
    text = text.replace(CAP, "");
    text = sub(&SPACE_RUNS, &text, " ");
    let text = text.trim_matches([' ', '\n']).to_string();
    if text.is_empty() {
        return String::new();
    }
    let mut text = if opts.capitalize { cap_lines(&text) } else { text };
    let last_line = text.rsplit('\n').next().unwrap_or("").to_string();
    let ends_alnum = text.chars().last().is_some_and(char::is_alphanumeric);
    if opts.end_punctuation && ends_alnum && !LIST_LINE.is_match(&last_line).unwrap_or(false) {
        text.push('.');
    }
    text
}

static SUBMIT: LazyLock<Regex> = LazyLock::new(|| re(r"(?i)(?:^|\s)submit[.!?,;]*\s*$"));

/// A take that ends with the word "submit" is stripped of it and sends
/// Enter. A hyphen before it ("pre-submit") doesn't count. Sentence
/// punctuation before it survives; a comma does not.
pub fn detect_submit(text: &str) -> (String, bool) {
    match SUBMIT.find(text).ok().flatten() {
        Some(m) => (
            text[..m.start()].trim_end_matches([' ', ',', ';']).to_string(),
            true,
        ),
        None => (text.to_string(), false),
    }
}

static WORD: LazyLock<Regex> = LazyLock::new(|| re(r"\b[\w']+\b"));

pub fn word_count(text: &str) -> usize {
    WORD.find_iter(text).filter(|m| m.is_ok()).count()
}
