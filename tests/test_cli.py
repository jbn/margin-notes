from __future__ import annotations

import json
import socket
import subprocess
import sys

import pytest
import uvicorn

from margin_notes import __version__, cli


@pytest.fixture
def run(monkeypatch):
    """Call cli.main without serving or opening a browser; return what uvicorn.run got."""
    calls: dict = {}
    opened: list[str] = []

    def fake_run(app, host, port, **kw):
        calls.update(app=app, host=host, port=port)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    monkeypatch.setattr(cli, "tailscale_status", lambda: None)  # tests never see this machine's tailnet
    monkeypatch.setattr(cli.webbrowser, "open", opened.append)

    class Timer:  # run the browser-open callback immediately
        def __init__(self, _delay, fn, args=()):
            self.fn, self.args = fn, args

        def start(self):
            self.fn(*self.args)

    monkeypatch.setattr(cli.threading, "Timer", Timer)

    def invoke(*argv: str) -> tuple[dict, list[str]]:
        cli.main(list(argv))
        return calls, opened

    return invoke


def test_folder(run, tree, capsys):
    calls, opened = run(str(tree), "--port", "0")
    assert calls["host"] == "127.0.0.1"
    out = capsys.readouterr()
    assert f"serving  {tree.resolve()}" in out.out
    assert opened == [f"http://127.0.0.1:{calls['port']}/"]
    assert "warning" not in out.err


def test_document_opens_its_url(run, tree):
    (tree / "my notes.md").write_text("# x\n", encoding="utf-8", newline="\n")
    calls, opened = run(str(tree / "my notes.md"), "--port", "0")
    assert opened == [f"http://127.0.0.1:{calls['port']}/my%20notes.md"]


def test_no_open(run, tree):
    _, opened = run(str(tree), "--no-open", "--port", "0")
    assert opened == []


def test_all_interfaces_warns_and_browses_locally(run, tree, capsys):
    calls, _ = run(str(tree), "--host", "0.0.0.0", "--port", "0", "--no-open")
    assert calls["host"] == "0.0.0.0"
    out = capsys.readouterr()
    assert f"open     http://127.0.0.1:{calls['port']}/" in out.out
    assert "no authentication" in out.err


def test_non_reviewable_file_is_served_with_a_note(run, tree, capsys):
    run(str(tree / "data.csv"), "--port", "0", "--no-open")
    assert "isn't Markdown or HTML" in capsys.readouterr().err


def test_missing_path():
    with pytest.raises(SystemExit, match="no such file or folder"):
        cli.main(["/definitely/not/here", "--no-open"])


def test_version(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--version"])
    assert e.value.code == 0
    assert capsys.readouterr().out.strip() == f"margin-notes {__version__}"


def test_free_port_skips_busy_ports():
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        taken = busy.getsockname()[1]
        assert cli.free_port("127.0.0.1", taken) != taken


@pytest.mark.parametrize(
    ("host", "loopback"),
    [
        ("127.0.0.1", True),
        ("localhost", True),
        ("::1", True),
        ("0.0.0.0", False),
        ("192.168.1.5", False),
        ("box", False),
    ],
)
def test_is_loopback(host, loopback):
    assert cli.is_loopback(host) is loopback


def test_module_entry_point():
    cmd = [sys.executable, "-m", "margin_notes", "--version"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == f"margin-notes {__version__}"


TS_STATUS = {
    "BackendState": "Running",
    "Self": {"DNSName": "box.example.ts.net.", "TailscaleIPs": ["100.64.0.7", "fd7a:115c:a1e0::7"]},
    "CurrentTailnet": {"MagicDNSEnabled": True},
}


class TestTailscale:
    def test_names_with_magic_dns(self):
        assert cli.tailscale_names(TS_STATUS) == ["box", "box.example.ts.net"]

    def test_names_without_magic_dns(self):
        status = {**TS_STATUS, "CurrentTailnet": {"MagicDNSEnabled": False}}
        assert cli.tailscale_names(status) == ["box.example.ts.net"]

    def test_names_fall_back_to_ipv4(self):
        status = {"BackendState": "Running", "Self": {"TailscaleIPs": ["fd7a::1", "100.64.0.7"]}}
        assert cli.tailscale_names(status) == ["100.64.0.7"]

    def test_no_tailscale(self):
        assert cli.tailscale_names(None) == []

    def test_status_without_the_cli(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cli.shutil, "which", lambda _: None)
        monkeypatch.setattr(cli, "TAILSCALE_APP", tmp_path / "missing")
        assert cli.tailscale_status() is None

    @pytest.mark.parametrize(
        "stdout, expected",
        [
            (json.dumps(TS_STATUS), TS_STATUS),
            (json.dumps({**TS_STATUS, "BackendState": "Stopped"}), None),
            ("not json", None),
            ("", None),
        ],
    )
    def test_status_parsing(self, monkeypatch, stdout, expected):
        monkeypatch.setattr(cli.shutil, "which", lambda _: "/usr/bin/tailscale")
        monkeypatch.setattr(cli.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0, stdout=stdout))
        assert cli.tailscale_status() == expected

    def test_status_times_out_quietly(self, monkeypatch):
        def hang(*a, **kw):
            raise subprocess.TimeoutExpired("tailscale", 2)

        monkeypatch.setattr(cli.shutil, "which", lambda _: "/usr/bin/tailscale")
        monkeypatch.setattr(cli.subprocess, "run", hang)
        assert cli.tailscale_status() is None

    def test_urls_when_serving_every_interface(self, run, tree, monkeypatch, capsys):
        monkeypatch.setattr(cli, "tailscale_status", lambda: TS_STATUS)
        calls, _ = run(str(tree), "--host", "0.0.0.0", "--no-open", "--port", "0")
        out = capsys.readouterr().out
        assert f"tailnet  http://box:{calls['port']}/" in out
        assert f"tailnet  http://box.example.ts.net:{calls['port']}/" in out

    def test_hint_when_serving_localhost(self, run, tree, monkeypatch, capsys):
        monkeypatch.setattr(cli, "tailscale_status", lambda: TS_STATUS)
        run(str(tree), "--no-open", "--port", "0")
        out = capsys.readouterr().out
        assert "tailnet  box, box.example.ts.net (add --host 0.0.0.0 to serve there)" in out
        assert "http://box" not in out

    def test_silent_without_tailscale(self, run, tree, capsys):
        run(str(tree), "--host", "0.0.0.0", "--no-open", "--port", "0")
        assert "tailnet" not in capsys.readouterr().out
