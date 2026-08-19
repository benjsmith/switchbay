"""Rail shell-detect must not treat chat replies as the unix `yes` command."""

from switchbay.daemon import _detect_shellish


def test_yes_is_not_shellish():
    assert _detect_shellish("yes") is False
    assert _detect_shellish("Yes") is False
    assert _detect_shellish("y") is False
    assert _detect_shellish("ok") is False
    assert _detect_shellish("no") is False


def test_real_commands_still_detect():
    assert _detect_shellish("ls") is True
    assert _detect_shellish("git status") is True
