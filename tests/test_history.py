import time

from freedictate.history import History


def test_add_search_stats_prune(tmp_path):
    h = History(tmp_path / "h.db")
    h.add("Hello world.", 2.0, "small.en", "notepad.exe", ts=time.time() - 40 * 86400)
    h.add("Second take with 100% effort_here.", 3.5)
    assert h.count() == 2
    assert [e.text for e in h.search("100%")] == ["Second take with 100% effort_here."]
    assert h.search("effort_") and not h.search("effortXhere")
    st = h.stats()
    assert st["count"] == 2 and st["words"] == 7 and st["words_week"] == 5
    assert h.prune(30) == 1
    assert h.count() == 1
    h.clear()
    assert h.count() == 0
    h.close()
