"""Command line: `margin-notes [PATH] [--host HOST] [--port PORT]`."""

from __future__ import annotations

import argparse
import contextlib
import ipaddress
import json
import shutil
import socket
import subprocess
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


# The Mac App Store build of Tailscale keeps its CLI inside the app bundle, off PATH.
TAILSCALE_APP = Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale")


def tailscale_status(timeout: float = 2.0) -> dict | None:
    """`tailscale status --json` from the Tailscale CLI, or None if it's absent, stopped or slow."""
    exe = shutil.which("tailscale") or (str(TAILSCALE_APP) if TAILSCALE_APP.is_file() else None)
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "status", "--json"], capture_output=True, text=True, timeout=timeout, check=False
        ).stdout
        status = json.loads(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if not isinstance(status, dict) or status.get("BackendState") != "Running":
        return None
    return status


def tailscale_names(status: dict | None) -> list[str]:
    """This machine's names on the tailnet: the MagicDNS short and full names, else its IPv4 address."""
    me = (status or {}).get("Self") or {}
    full = str(me.get("DNSName") or "").rstrip(".")
    magic_dns = ((status or {}).get("CurrentTailnet") or {}).get("MagicDNSEnabled")
    names = [full.split(".")[0], full] if full and magic_dns else [full] if full else []
    if not names:
        names = [ip for ip in me.get("TailscaleIPs") or [] if ":" not in ip][:1]
    return list(dict.fromkeys(names))


def tailscale_ips(status: dict | None) -> set[str]:
    return set(((status or {}).get("Self") or {}).get("TailscaleIPs") or [])


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
    every_interface = args.host in ("0.0.0.0", "::")
    if every_interface:
        lan = lan_address()
        if lan:
            print(f"  network  http://{lan}:{port}{start_path}")
    ts = tailscale_status()
    ts_names = tailscale_names(ts)
    if every_interface or args.host in tailscale_ips(ts) or args.host in ts_names:
        for name in ts_names:
            print(f"  tailnet  http://{name}:{port}{start_path}")
    elif ts_names:
        print(f"  tailnet  {', '.join(ts_names)} (add --host 0.0.0.0 to serve there)")
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
