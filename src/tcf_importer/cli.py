"""Command-line interface and foreground watcher."""
from __future__ import annotations

import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .core import (DEFAULT_CONFIG, DEFAULTS, Deferred, Importer, InvalidNote,
                   directory, eligible, load_config, notify, snapshot, validate)

LOG = logging.getLogger("tcf_importer")


def configure_logging(cfg):
    with directory(cfg["log_dir"], create=True):
        pass
    handler = RotatingFileHandler(cfg["log_dir"] / "importer.log", maxBytes=2_000_000, backupCount=3)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOG.setLevel(logging.INFO)
    LOG.addHandler(handler)


def setup(path):
    if path.exists():
        print(f"Configuration already exists: {path}")
        load_config(path)
        return
    answer = input("Existing Obsidian vault directory: ").strip()
    if not answer:
        raise ValueError("Vault path is required")
    vault = Path(answer).expanduser().absolute()
    if not vault.is_dir():
        raise ValueError("Vault directory must already exist; no vault was created")
    # Validate settings before persisting anything.
    values = DEFAULTS | {"vault": str(vault)}
    text = "\n".join(f"{key} = {json.dumps(value)}" for key, value in values.items()) + "\n"
    import tempfile
    with tempfile.TemporaryDirectory(prefix="tcf-setup-") as temp:
        candidate = Path(temp) / "config.toml"
        candidate.write_text(text)
        cfg = load_config(candidate)
        with directory(cfg["vault"]):
            pass
    from .core import publish
    with directory(path.absolute().parent, create=True) as parent:
        publish(parent, path.name, text.encode())
    for key in ("inbox", "quarantine", "processed", "log_dir"):
        with directory(cfg[key], create=True):
            pass
    print(f"Saved {path}. No service was enabled or started.")


def scan(inbox):
    with directory(inbox):
        return sorted(path for path in inbox.iterdir() if eligible(path))


class InboxEvents(FileSystemEventHandler):
    def __init__(self, wake):
        self.wake = wake

    def on_any_event(self, event):
        # Opening files during scans must not trigger another scan.
        if event.event_type in ("created", "modified", "moved", "deleted"):
            self.wake.set()


def watch(cfg):
    importer = Importer(cfg)
    with directory(cfg["inbox"], create=True):
        pass
    wake, stopped = threading.Event(), threading.Event()
    observer = Observer()
    observer.schedule(InboxEvents(wake), str(cfg["inbox"]), recursive=False)
    def stop(*_):
        stopped.set()
        wake.set()
    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    failures = {}
    observer.start()
    LOG.info("Watching %s", cfg["inbox"])
    try:
        while not stopped.is_set():
            wake.clear()
            for path in scan(cfg["inbox"]):
                if stopped.is_set():
                    break
                try:
                    importer.process(path)
                    failures.pop(path, None)
                except (Deferred, FileNotFoundError):
                    LOG.debug("Deferred %s", path)
                except InvalidNote:
                    pass  # Already quarantined, logged, and notified.
                except (OSError, ValueError) as exc:
                    LOG.error("Import failed for %s: %s", path, exc)
                    if failures.get(path) != str(exc):
                        notify(cfg, "TCF import failed", f"{path.name}: {exc}")
                        failures[path] = str(exc)
            wake.wait(cfg["poll_interval_seconds"])
    finally:
        observer.stop()
        observer.join()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def status(cfg):
    print(f"Vault: {cfg['vault']}")
    print(f"Inbox: {cfg['inbox']}")
    print(f"Processed archive: {cfg['processed']}")
    print(f"Pending notes: {len(scan(cfg['inbox'])) if cfg['inbox'].exists() else 0}")
    try:
        result = subprocess.run(["systemctl", "--user", "is-active", "tcf-importer.service"],
                                capture_output=True, text=True, timeout=5)
        print(f"Service: {result.stdout.strip() or 'unavailable'}")
    except (OSError, subprocess.SubprocessError):
        print("Service: unavailable")
    log = cfg["log_dir"] / "importer.log"
    if log.exists():
        errors = [line for line in log.read_text(errors="replace").splitlines() if " ERROR " in line]
        if errors:
            print("Recent failures:\n" + "\n".join(errors[-5:]))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Import local TCF learning notes into Obsidian")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("setup", "watch", "status"):
        commands.add_parser(command)
    for command in ("validate", "dry-run", "import"):
        commands.add_parser(command).add_argument("file", type=Path)
    args = parser.parse_args(argv)
    cfg = None
    try:
        if args.command == "setup":
            setup(args.config.expanduser())
        elif args.command == "validate":
            validate(snapshot(args.file.expanduser().absolute())[0])
            print(f"Valid: {args.file}")
        else:
            cfg = load_config(args.config.expanduser())
            if args.command in ("watch", "import"):
                configure_logging(cfg)
            if args.command == "watch":
                watch(cfg)
            elif args.command == "status":
                status(cfg)
            else:
                print(Importer(cfg).process(args.file, dry_run=args.command == "dry-run"))
        return 0
    except InvalidNote as exc:
        print(f"Invalid note: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        if cfg and args.command in ("watch", "import"):
            LOG.error("%s", exc)
            notify(cfg, "TCF import failed", str(exc))
        return 2
    except KeyboardInterrupt:
        return 130
