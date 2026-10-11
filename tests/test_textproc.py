from freedictate.textproc import clean, word_count


def test_removes_fillers_and_capitalizes():
    assert clean("um so I think uh we should go") == "So I think we should go."


def test_keeps_meaningful_words():
    assert clean("I like it, you know") == "I like it, you know."


def test_voice_commands_keep_the_speakers_punctuation():
    assert clean("Dear John, new line. Thanks for the note. New paragraph. Best") == \
        "Dear John,\nThanks for the note.\n\nBest."


def test_voice_commands_off_leaves_words():
    assert clean("type new line here", voice_commands=False) == "Type new line here."


def test_replacements_match_whole_words_any_case():
    reps = [{"find": "api", "replace": "API"}, {"find": "free dictate", "replace": "FreeDictate"}]
    assert clean("the api of free dictate rapid", replacements=reps) == "The API of FreeDictate rapid."


def test_end_punctuation_only_when_missing():
    assert clean("is it done?") == "Is it done?"
    assert clean("done", end_punctuation=False) == "Done"


def test_filler_only_take_is_empty():
    assert clean("Um.") == ""
    assert clean("   ") == ""


def test_word_count():
    assert word_count("Don't stop, it's 3 o'clock.") == 5
