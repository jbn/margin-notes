"""Command line: `margin-notes [PATH] [--host HOST] [--port PORT]`."""

from __future__ import annotations

import argparse
import contextlib
import ipaddress
import socket
import sys
import threading
import webbrowser
from pathlib import Path
from urllib.parse import quote

from . import __version__
from .server import create_app, is_reviewable


def free_port(host: str, start: int) -> int:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    for port in range(start, start + 50):
        with socket.socket(family) as s:
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    raise SystemExit(f"margin-notes: no free port in {start}-{start + 49} on {host}")


def lan_address() -> str | None:
    # A UDP "connect" picks the outbound interface without sending anything.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            return s.getsockname()[0]
    except OSError:
        return None


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        prog="margin-notes",
        description="Serve a folder or a document, highlight and comment on HTML and Markdown, "
        "and save the notes as <document>.notes.json beside each one.",
    )
    ap.add_argument(
        "path", nargs="?", default=".", type=Path, help="a folder to browse or a document to open (default: .)"
    )
    ap.add_argument(
        "--host", default="127.0.0.1", help="interface to bind; 0.0.0.0 exposes it to your network (default: 127.0.0.1)"
    )
    ap.add_argument("-p", "--port", type=int, default=8765, help="first port to try (default: 8765)")
    ap.add_argument("--no-open", action="store_true", help="don't open a browser")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)  # show the banner even when piped

    import uvicorn  # deferred so --help and --version stay fast

    target = args.path.expanduser().resolve()
    if not target.exists():
        raise SystemExit(f"margin-notes: no such file or folder: {target}")
    if target.is_dir():
        root, start_path = target, "/"
    else:
        root, start_path = target.parent, "/" + quote(target.name)
        if not is_reviewable(target):
            print(f"margin-notes: {target.name} isn't Markdown or HTML; it will be served as-is.", file=sys.stderr)

    port = free_port(args.host, args.port)
    browse_host = "127.0.0.1" if args.host in ("0.0.0.0", "::", "") else args.host
    url = f"http://{f'[{browse_host}]' if ':' in browse_host else browse_host}:{port}{start_path}"

    print(f"margin-notes {__version__}")
    print(f"  serving  {root}")
    print(f"  open     {url}")
    if args.host in ("0.0.0.0", "::"):
        lan = lan_address()
        if lan:
            print(f"  network  http://{lan}:{port}{start_path}")
    if not is_loopback(args.host):
        print(
            "  warning  anyone who can reach this address can read every file under the folder "
            "and add notes. There is no authentication.",
            file=sys.stderr,
        )
    print("  Ctrl-C to stop")

    if not args.no_open:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    with contextlib.suppress(KeyboardInterrupt):
        uvicorn.run(create_app(root), host=args.host, port=port, log_level="warning")
