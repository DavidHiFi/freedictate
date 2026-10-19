// Pure output tests. deliver(), type_text() and the clipboard setters drive
// the real Windows clipboard and keyboard, so they are only exercised in live
// use (Python has no test_output.py either). What is checkable without side
// effects is the clipboard-format contract those calls rely on.

use freedictate_rust::output;

#[test]
fn cf_unicodetext_is_the_winapi_value() {
    // deliver() writes and get_clipboard_text() reads this exact format id.
    assert_eq!(output::CF_UNICODETEXT, 13);
}

#[test]
fn transient_clipboard_formats_register_stably() {
    // The three marker names behind the transient flag must register to fixed,
    // distinct ids; a typo would silently stop Win+V and clipboard managers
    // from skipping our text. RegisterClipboardFormatW is idempotent and does
    // not open or change the clipboard.
    let ids: Vec<u32> = output::TRANSIENT_FORMATS.iter().map(|n| output::registered(n)).collect();
    assert!(ids.iter().all(|id| *id != 0), "all three formats must register");
    assert_eq!(ids[0], output::registered(output::TRANSIENT_FORMATS[0]), "registration is stable");
    assert_ne!(ids[0], ids[1]);
    assert_ne!(ids[1], ids[2]);
}
