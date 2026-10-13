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


def test_repeats_collapse_stumbles_but_keep_meaningful_doubles():
    assert clean("make sure the the entire app works", repeats=True) == "Make sure the entire app works."
    assert clean("I want, I want to open up my game open up my game now", repeats=True) == \
        "I want to open up my game now."
    assert clean("The the cat sat", repeats=True) == "The cat sat."
    assert clean("really really quickly, they had had enough", repeats=True) == \
        "Really really quickly, they had had enough."
    assert clean("what it is is fine", repeats=True) == "What it is is fine."
    assert clean("the the cat", repeats=False) == "The the cat."


def test_repeats_stop_at_a_sentence_end():
    assert clean("Go home. Go home now", repeats=True) == "Go home. Go home now."


def test_spoken_punctuation_replaces_whispers_guess():
    assert clean("Hello, comma, how are you question mark? I'm fine full stop. thanks") == \
        "Hello, how are you? I'm fine. Thanks."
    assert clean("well hyphen known file underscore name") == "Well-known file_name."
    assert clean("open bracket optional close bracket and open quote hi there close quote said") == \
        "(optional) and \"hi there\" said."


def test_spoken_dot_points_build_a_list():
    assert clean("my shopping list colon dot point milk dot point eggs dot point bread") == \
        "My shopping list:\n- Milk\n- Eggs\n- Bread"
    assert clean("Things to do. New line. Dot point fix it") == "Things to do.\n- Fix it"
    assert clean("Intro new paragraph dot point a dot point b") == "Intro\n\n- A\n- B"


def test_literal_types_the_word():
    assert clean("type literal comma here and a comma here") == "Type comma here and a, here."


def test_words_containing_commands_are_untouched():
    assert clean("the dashboard has a colonnade") == "The dashboard has a colonnade."
