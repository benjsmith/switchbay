"""Quiet access logger + size-bounded daemon log."""

from __future__ import annotations

import logging
import logging.handlers
import sys

from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from aiohttp.web_log import AccessLogger

from switchbay import daemonlog


def test_should_log_access_drops_poller_success():
    assert daemonlog.should_log_access("/api/health", 200) is False
    assert daemonlog.should_log_access("/api/health", 304) is False
    assert daemonlog.should_log_access("/api/runs/active", 200) is False


def test_should_log_access_keeps_poller_errors_and_other_paths():
    assert daemonlog.should_log_access("/api/health", 500) is True
    assert daemonlog.should_log_access("/api/health", 503) is True
    assert daemonlog.should_log_access("/api/runs/active", 404) is True
    assert daemonlog.should_log_access("/api/tree", 200) is True
    assert daemonlog.should_log_access("/api/file", 200) is True


def test_log_path_honours_env(tmp_path, monkeypatch):
    target = tmp_path / "nested" / "d.log"
    monkeypatch.setenv("SWITCHBAY_DAEMON_LOG", str(target))
    assert daemonlog.log_path() == target


def test_quiet_access_logger_skips_health_200():
    lg = logging.getLogger("test.aiohttp.access.skip")
    lg.handlers.clear()
    lg.propagate = False
    lg.setLevel(logging.INFO)
    recs: list[logging.LogRecord] = []

    class H(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            recs.append(record)

    lg.addHandler(H())
    al = daemonlog.QuietAccessLogger(lg, AccessLogger.LOG_FORMAT)
    req = make_mocked_request("GET", "/api/health")
    al.log(req, web.Response(status=200), 0.001)
    assert recs == []


def test_quiet_access_logger_keeps_health_500_and_other_200():
    lg = logging.getLogger("test.aiohttp.access.keep")
    lg.handlers.clear()
    lg.propagate = False
    lg.setLevel(logging.INFO)
    recs: list[logging.LogRecord] = []

    class H(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            recs.append(record)

    lg.addHandler(H())
    al = daemonlog.QuietAccessLogger(lg, AccessLogger.LOG_FORMAT)
    al.log(make_mocked_request("GET", "/api/health"), web.Response(status=500), 0.001)
    al.log(make_mocked_request("GET", "/api/tree"), web.Response(status=200), 0.001)
    assert len(recs) == 2


def test_configure_writes_rotating_file(tmp_path, monkeypatch):
    path = tmp_path / "switchbay-daemon.log"
    monkeypatch.setenv("SWITCHBAY_DAEMON_LOG", str(path))
    stdout, stderr = sys.stdout, sys.stderr
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    try:
        got = daemonlog.configure(console=False)
        assert got == path
        logging.getLogger("switchbay.daemon").info("boot probe")
        text = path.read_text(encoding="utf-8")
        assert "boot probe" in text
        rot = [
            h for h in root.handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        assert len(rot) == 1
        assert rot[0].maxBytes == daemonlog.LOG_MAX_BYTES
        assert rot[0].backupCount == daemonlog.LOG_BACKUP_COUNT
    finally:
        for h in list(root.handlers):
            root.removeHandler(h)
            h.close()
        for h in saved_handlers:
            root.addHandler(h)
        root.setLevel(saved_level)
        sys.stdout, sys.stderr = stdout, stderr


def test_configure_drops_oversized_haystack(tmp_path, monkeypatch):
    monkeypatch.setattr(daemonlog, "LOG_MAX_BYTES", 1024)
    path = tmp_path / "switchbay-daemon.log"
    path.write_bytes(b"x" * 2048)
    monkeypatch.setenv("SWITCHBAY_DAEMON_LOG", str(path))
    stdout, stderr = sys.stdout, sys.stderr
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    try:
        daemonlog.configure(console=False)
        logging.getLogger("switchbay.daemon").info("fresh")
        assert path.stat().st_size < 4096
        assert "fresh" in path.read_text(encoding="utf-8")
        assert not path.with_name(path.name + ".1").exists()
    finally:
        for h in list(root.handlers):
            root.removeHandler(h)
            h.close()
        for h in saved_handlers:
            root.addHandler(h)
        root.setLevel(saved_level)
        sys.stdout, sys.stderr = stdout, stderr
