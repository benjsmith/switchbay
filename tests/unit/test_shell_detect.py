"""Rail shell-detect must not treat chat replies as the unix `yes` command."""

from switchbay.daemon import _detect_shellish


def test_yes_is_not_shellish():
    assert _detect_shellish("yes") is False
    assert _detect_shellish("Yes") is False
    assert _detect_shellish("y") is False
    assert _detect_shellish("ok") is False
    assert _detect_shellish("no") is False


def test_question_words_are_not_shellish():
    """macOS ships /usr/bin/what and /usr/bin/who; typing 'what' in
    the rail must stay chat, not spawn a shell thread."""
    assert _detect_shellish("what") is False
    assert _detect_shellish("what do we know about active learning") is False
    assert _detect_shellish("who wrote this") is False
    assert _detect_shellish("which model should I use") is False
    assert _detect_shellish("how does this work") is False
    assert _detect_shellish("where is the charter") is False
    assert _detect_shellish("why did the sweep fail") is False
    assert _detect_shellish("when was this ingested") is False
    assert _detect_shellish("hello") is False


def test_real_commands_still_detect():
    assert _detect_shellish("ls") is True
    assert _detect_shellish("git status") is True
    assert _detect_shellish("whoami") is True
    assert _detect_shellish("pwd") is True
