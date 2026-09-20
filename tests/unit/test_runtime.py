"""Shared PATH / executable discovery under launchd-minimal PATH."""

from __future__ import annotations

import os
from pathlib import Path

from switchbay import runtime

_MINIMAL_PATH = os.pathsep.join(("/usr/bin", "/bin"))


def _exe(path: Path, body: str = "#!/bin/sh\nexit 0\n") -> Path:
    if os.name == "nt" and path.suffix == "":
        path = path.with_suffix(".exe")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


def _assert_exe(actual: str | None, expected: Path) -> None:
    # shutil.which may return node.EXE (PATHEXT) vs fixture node.exe; Path
    # equality is case-folded on Windows and exact on POSIX.
    assert actual is not None
    assert Path(actual) == expected


def test_minimal_launchd_path_finds_nvm_node(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    nvm_bin = home / ".nvm" / "versions" / "node" / "v22.11.0" / "bin"
    node = _exe(nvm_bin / "node")
    (home / ".nvm" / "alias").mkdir(parents=True)
    (home / ".nvm" / "alias" / "default").write_text("22.11.0\n", encoding="utf-8")
    monkeypatch.setattr(runtime, "_SYSTEM_BIN_DIRS", ())
    env = {
        "PATH": _MINIMAL_PATH,
        "HOME": str(home),
        "NVM_DIR": str(home / ".nvm"),
    }
    found = runtime.resolve_node(env, home=home)
    _assert_exe(found, node)


def test_empty_nvm_alias_does_not_crash(tmp_path: Path):
    alias = tmp_path / ".nvm" / "alias" / "default"
    alias.parent.mkdir(parents=True)
    alias.write_text("", encoding="utf-8")
    assert runtime._nvm_bin_dirs(home=tmp_path, environ={}) == []


def test_nvm_major_partial_and_lts_star(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    v22 = _exe(home / ".nvm" / "versions" / "node" / "v22.17.0" / "bin" / "node")
    _exe(home / ".nvm" / "versions" / "node" / "v22.11.0" / "bin" / "node")
    alias = home / ".nvm" / "alias"
    alias.mkdir(parents=True)
    (alias / "lts").mkdir()
    (alias / "lts" / "iron").write_text("22\n", encoding="utf-8")
    # nvm's current-LTS pointer is a file named '*'; Windows rejects that name.
    try:
        (alias / "lts" / "*").write_text("iron\n", encoding="utf-8")
    except OSError:
        (alias / "default").write_text("iron\n", encoding="utf-8")
    else:
        (alias / "default").write_text("lts/*\n", encoding="utf-8")
    monkeypatch.setattr(runtime, "_SYSTEM_BIN_DIRS", ())
    env = {
        "PATH": _MINIMAL_PATH,
        "HOME": str(home),
        "NVM_DIR": str(home / ".nvm"),
    }
    found = runtime.resolve_node(env, home=home)
    _assert_exe(found, v22)


def test_selected_path_precedes_fallback(tmp_path: Path, monkeypatch):
    chosen = _exe(tmp_path / "chosen" / "node")
    fallback = _exe(tmp_path / "fallback" / "node")
    monkeypatch.setattr(runtime, "_SYSTEM_BIN_DIRS", (str(fallback.parent),))
    monkeypatch.setattr(runtime, "_nvm_bin_dirs", lambda **kw: [])
    monkeypatch.setattr(runtime, "_version_manager_dirs", lambda **kw: [])
    _assert_exe(
        runtime.resolve_node({"PATH": str(chosen.parent)}, home=tmp_path),
        chosen,
    )


def test_missing_node_isolates_homebrew(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(runtime, "_SYSTEM_BIN_DIRS", ())
    monkeypatch.setattr(runtime, "_nvm_bin_dirs", lambda **kw: [])
    monkeypatch.setattr(runtime, "_version_manager_dirs", lambda **kw: [])
    assert runtime.resolve_node(
        {"PATH": _MINIMAL_PATH, "HOME": str(tmp_path)}, home=tmp_path,
    ) is None


def test_explicit_node_survives_reenrich_and_governs_env_node(tmp_path: Path, monkeypatch):
    chosen = _exe(tmp_path / "chosen" / "node")
    fallback = _exe(tmp_path / "fallback" / "node")
    monkeypatch.setattr(runtime, "_SYSTEM_BIN_DIRS", (str(fallback.parent),))
    monkeypatch.setattr(runtime, "_nvm_bin_dirs", lambda **kw: [])
    monkeypatch.setattr(runtime, "_version_manager_dirs", lambda **kw: [])
    env = {
        "PATH": _MINIMAL_PATH,
        "SWITCHBAY_NODE": str(chosen),
        "HOME": str(tmp_path),
    }
    spawned = runtime.spawn_env(env, home=tmp_path)
    parts = spawned["PATH"].split(os.pathsep)
    assert parts[0] == str(chosen.parent)
    _assert_exe(runtime.resolve_node(spawned, home=tmp_path), chosen)
    again = runtime.enrich_env(spawned, home=tmp_path)
    _assert_exe(runtime.resolve_node(again, home=tmp_path), chosen)


def test_nvm_bin_env_wins_over_default_alias(tmp_path: Path):
    home = tmp_path / "home"
    active = _exe(tmp_path / "active" / "node")
    other = _exe(home / ".nvm" / "versions" / "node" / "v20.0.0" / "bin" / "node")
    env = {
        "PATH": _MINIMAL_PATH,
        "HOME": str(home),
        "NVM_BIN": str(active.parent),
        "NVM_DIR": str(home / ".nvm"),
    }
    found = runtime.resolve_node(env, home=home)
    _assert_exe(found, active)
    assert Path(found) != other


def test_explicit_node_env_wins(tmp_path: Path):
    chosen = _exe(tmp_path / "custom dir" / "node")
    decoy = _exe(tmp_path / "opt" / "homebrew" / "bin" / "node")
    env = {
        "PATH": _MINIMAL_PATH,
        "SWITCHBAY_NODE": str(chosen),
        "HOME": str(tmp_path),
    }
    found = runtime.resolve_node(env, home=tmp_path, extra_dirs=(str(decoy.parent),))
    _assert_exe(found, chosen)


def test_spaces_in_home_and_runtime_dir(tmp_path: Path):
    home = tmp_path / "User Name"
    volta = _exe(home / ".volta" / "bin" / "node")
    env = {"PATH": _MINIMAL_PATH, "HOME": str(home), "VOLTA_HOME": str(home / ".volta")}
    found = runtime.resolve_node(env, home=home)
    _assert_exe(found, volta)


def test_pnpm_home_and_missing_non_executable(tmp_path: Path):
    home = tmp_path / "home"
    pnpm = _exe(home / "Library" / "pnpm" / "pnpm")
    env = {"PATH": _MINIMAL_PATH, "HOME": str(home), "PNPM_HOME": str(pnpm.parent)}
    _assert_exe(runtime.resolve_pnpm(env, home=home), pnpm)
    missing = runtime.resolve_executable(
        "no-such-bin-xyz-switchbay", {"PATH": _MINIMAL_PATH}, home=home,
    )
    assert missing is None
    not_exec = tmp_path / "bin" / "not-a-node"
    not_exec.parent.mkdir(parents=True)
    not_exec.write_text("not executable\n", encoding="utf-8")
    not_exec.chmod(0o644)
    assert runtime.is_executable(not_exec) is False
    assert runtime.resolve_executable(
        "not-a-node",
        {"PATH": str(not_exec.parent)},
        extra_dirs=(),
        home=home,
    ) is None


def test_enrich_env_existing_path_beats_fallback(tmp_path: Path):
    extra = tmp_path / "opt" / "homebrew" / "bin"
    extra.mkdir(parents=True)
    env = {"PATH": _MINIMAL_PATH, "HOME": str(tmp_path)}
    out = runtime.enrich_env(env, extra_dirs=(str(extra),), home=tmp_path)
    parts = out["PATH"].split(os.pathsep)
    assert parts[0] == "/usr/bin"
    assert str(extra) in parts
    assert "/bin" in parts


def test_enrich_env_prepend_wins_over_path(tmp_path: Path):
    extra = tmp_path / "opt" / "homebrew" / "bin"
    extra.mkdir(parents=True)
    chosen = tmp_path / "chosen"
    chosen.mkdir()
    env = {"PATH": _MINIMAL_PATH, "HOME": str(tmp_path)}
    out = runtime.enrich_env(
        env, extra_dirs=(str(extra),), prepend=(str(chosen),), home=tmp_path,
    )
    parts = out["PATH"].split(os.pathsep)
    assert parts[0] == str(chosen)
    assert "/usr/bin" in parts
    assert str(extra) in parts


def test_updater_child_env_uses_runtime(tmp_path: Path, monkeypatch):
    from switchbay import updater
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", _MINIMAL_PATH)
    env = updater.child_env()
    assert "/usr/bin" in env["PATH"]
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["NPM_CONFIG_YES"] == "true"


def test_service_runtime_exports_custom_dirs_and_spaces(tmp_path: Path, monkeypatch):
    node = _exe(tmp_path / "custom runtime" / "node-bin" / "node")
    pnpm = _exe(tmp_path / "custom pnpm" / "pnpm")
    monkeypatch.setattr(runtime, "_SYSTEM_BIN_DIRS", ())
    monkeypatch.setattr(runtime, "_nvm_bin_dirs", lambda **kw: [])
    monkeypatch.setattr(runtime, "_version_manager_dirs", lambda **kw: [])
    env = {
        "PATH": _MINIMAL_PATH,
        "HOME": str(tmp_path),
        "NVM_BIN": str(node.parent),
        "PNPM_HOME": str(pnpm.parent),
        "SWITCHBAY_NODE": str(node),
        "SECRET_TOKEN": "do-not-copy",
    }
    out = runtime.service_runtime_exports(environ=env, home=tmp_path)
    assert out["NVM_BIN"] == str(node.parent)
    assert out["PNPM_HOME"] == str(pnpm.parent)
    assert out["SWITCHBAY_NODE"] == str(node)
    assert "SECRET_TOKEN" not in out
    parts = out["PATH"].split(os.pathsep)
    assert parts[:4] == ["/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    assert str(node.parent) in parts
    assert str(pnpm.parent) in parts
    assert "/opt/homebrew/bin" not in parts
