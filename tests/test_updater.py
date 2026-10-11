from freedictate import updater


def test_version_order():
    assert updater.newer("3.0.1", "3.0.0")
    assert updater.newer("v3.1.0", "3.0.9")
    assert not updater.newer("3.0.0", "3.0.0")
    assert updater.newer("3.0.0", "3.0.0-beta.2")
    assert updater.newer("3.0.0-beta.3", "3.0.0-beta.2")
    assert not updater.newer("2.9", "3.0.0")


def test_asset_choice():
    rel = updater.Release("3.1.0", "v3.1.0", "", "", "", False,
                          {"FreeDictate-3.1.0-Setup.exe": "u1", "FreeDictate-3.1.0-portable.zip": "u2",
                           "SHA256SUMS.txt": "u3"})
    assert updater._asset(rel, portable=False) == ("FreeDictate-3.1.0-Setup.exe", "u1")
    assert updater._asset(rel, portable=True) == ("FreeDictate-3.1.0-portable.zip", "u2")
