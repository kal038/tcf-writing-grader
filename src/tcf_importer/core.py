"""Validation and durable filesystem operations. Never interpret note content as code."""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import stat
import subprocess
import time
import tomllib
import uuid

import yaml

LOG = logging.getLogger("tcf_importer")
DEFAULT_CONFIG = Path.home() / ".config/tcf-importer/config.toml"
DEFAULTS = dict(inbox="~/Downloads/TCF-Inbox", vault="",
                quarantine="~/Downloads/TCF-Inbox-Rejected",
                log_dir="~/.local/state/tcf-importer", notifications=True,
                poll_interval_seconds=30)
SECTIONS = ("Reusable Vocabulary and Collocations", "Reusable Grammar",
            "Notable Personal Mistakes", "Active Recall and Transfer")
MAX_BYTES = 10 * 1024 * 1024


class InvalidNote(ValueError):
    pass


class Deferred(OSError):
    """A source changed or is not yet ready."""


class StrictLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise InvalidNote("YAML keys must be unique strings")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def validate(data: bytes) -> dict:
    if len(data) > MAX_BYTES:
        raise InvalidNote("Note exceeds 10 MiB limit")
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise InvalidNote("Note must be UTF-8") from exc
    if not lines or lines[0] != "---":
        raise InvalidNote("File must begin with YAML frontmatter delimiter ---")
    try:
        end = lines.index("---", 1)
        meta = yaml.load("\n".join(lines[1:end]), Loader=StrictLoader)
    except (ValueError, yaml.YAMLError, RecursionError) as exc:
        raise InvalidNote(f"Invalid frontmatter: {exc}") from exc
    if not isinstance(meta, dict):
        raise InvalidNote("Frontmatter must be a mapping")
    if meta.get("type") != "tcf-learning":
        raise InvalidNote("type must be tcf-learning")
    if type(meta.get("schema_version")) is not int or meta["schema_version"] != 1:
        raise InvalidNote("schema_version must be integer 1")
    if type(meta.get("task")) is not int or meta["task"] not in (1, 2, 3):
        raise InvalidNote("task must be integer 1, 2, or 3")
    if not isinstance(meta.get("topic"), str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", meta["topic"]):
        raise InvalidNote("topic must be a lowercase-hyphenated slug")
    date = meta.get("date")
    if type(date) is dt.date:
        date = date.isoformat()
    try:
        if not isinstance(date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise ValueError()
        dt.date.fromisoformat(date)
    except ValueError as exc:
        raise InvalidNote("date must be a valid YYYY-MM-DD date") from exc
    if meta.get("level") not in ("B1", "B2", "C1", "unknown"):
        raise InvalidNote("level must be B1, B2, C1, or unknown")
    if not isinstance(meta.get("tags"), list) or not all(isinstance(t, str) for t in meta["tags"]):
        raise InvalidNote("tags must be an array of strings")
    sections, current, fence = {}, None, None
    for line in lines[end + 1:]:
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
            elif current:
                sections[current].append(line)
            continue
        if marker:
            fence = marker[1]
            continue
        heading = re.match(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$", line)
        if heading and len(heading[1]) <= 2:
            current = heading[2] if heading[1] == "##" and heading[2] in SECTIONS else None
            if current:
                if current in sections:
                    raise InvalidNote(f"Duplicate section: {current}")
                sections[current] = []
        elif current:
            sections[current].append(line)
    for section in SECTIONS:
        if not "\n".join(sections.get(section, [])).strip():
            raise InvalidNote(f"Missing or empty section: {section}")
    return meta


def load_config(path: Path) -> dict:
    with path.open("rb") as stream:
        cfg = DEFAULTS | tomllib.load(stream)
    for key in ("inbox", "vault", "quarantine", "log_dir"):
        if not isinstance(cfg[key], str) or not cfg[key].strip():
            raise ValueError(f"Configure {key} in {path}")
        cfg[key] = Path(cfg[key]).expanduser().absolute()
    if not cfg["vault"].is_dir():
        raise ValueError("Configured vault must already exist")
    if type(cfg["notifications"]) is not bool:
        raise ValueError("notifications must be a boolean")
    interval = cfg["poll_interval_seconds"]
    if type(interval) not in (int, float) or not 0 < interval < float("inf"):
        raise ValueError("poll_interval_seconds must be positive and finite")
    paths = [cfg[k].resolve() for k in ("inbox", "vault", "quarantine", "log_dir")]
    for i, a in enumerate(paths):
        for b in paths[i + 1:]:
            if a == b or a in b.parents or b in a.parents:
                raise ValueError("Inbox, vault, quarantine, and log_dir must not overlap")
    return cfg


@contextlib.contextmanager
def directory(path: Path, create=False):
    """Walk absolute paths with no-follow directory descriptors."""
    path = path.absolute()
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            if part in (".", ".."):
                raise ValueError("Unsafe path component")
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                    os.fsync(fd)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def snapshot(path: Path):
    with directory(path.parent) as parent:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("Source must be a regular file")
            data = stream.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError("File exceeds 10 MiB; left in place for manual review")
            after = os.fstat(stream.fileno())
    signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    if signature(before) != signature(after):
        raise Deferred("File changed while reading")
    return data, signature(after)


def stable_read(path: Path, delay=1):
    previous = snapshot(path)
    for _ in range(2):
        time.sleep(delay)
        current = snapshot(path)
        if current != previous:
            raise Deferred("Waiting for stable contents")
    return previous


def eligible(path: Path) -> bool:
    return (not path.name.startswith(".") and path.suffix == ".md"
            and not re.search(r"(?:\.tmp|\.part|\.swp|~)\.md$", path.name)
            and not path.is_symlink() and path.is_file())


def safe_name(name: str) -> str:
    name = re.sub(r'[\x00-\x1f\x7f/\\:<>"|?*]', "_", name).lstrip(". ")
    # Bound UTF-8 length below NAME_MAX, leaving room for collision suffixes.
    stem = Path(name).stem.encode("utf-8")[:180].decode("utf-8", "ignore").rstrip(". ")
    return (stem or "lesson") + ".md"


def publish(parent: int, name: str, data: bytes):
    """Durable, atomic, no-overwrite publication, entirely on target filesystem."""
    stage = ".tcf-stage-" + uuid.uuid4().hex
    fd = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(stage, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
        os.fsync(parent)
    finally:
        os.unlink(stage, dir_fd=parent)
        os.fsync(parent)


def atomic_json(parent: int, name: str, value: dict):
    stage = ".tcf-json-" + uuid.uuid4().hex
    try:
        publish(parent, stage, json.dumps(value, ensure_ascii=False).encode())
        os.replace(stage, name, src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)
    finally:
        try:
            os.unlink(stage, dir_fd=parent)
        except FileNotFoundError:
            pass


def notify(cfg, title, message):
    if cfg["notifications"]:
        try:
            subprocess.run(["notify-send", "--app-name=TCF Importer", "--", title, message],
                           timeout=5, check=True, capture_output=True)
        except (OSError, subprocess.SubprocessError):
            LOG.warning("Desktop notification unavailable")


class Importer:
    def __init__(self, cfg):
        self.cfg = cfg
        self.receipts = cfg["log_dir"] / "receipts"

    @contextlib.contextmanager
    def lock(self):
        with directory(self.cfg["log_dir"], create=True) as parent:
            fd = os.open("import.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=parent)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                os.close(fd)

    def target(self, meta):
        return self.cfg["vault"] / "TCF Canada" / "Writing" / "Learnings" / f"Task-{meta['task']}"

    def receipt_name(self, data):
        return hashlib.sha256(os.fsencode(self.cfg["vault"].resolve()) + b"\0" + data).hexdigest() + ".json"

    def receipt(self, name):
        try:
            raw, _ = snapshot(self.receipts / name)
            return json.loads(raw)
        except FileNotFoundError:
            return None

    def matches(self, target, data):
        try:
            return snapshot(target)[0] == data
        except (OSError, ValueError):
            return False

    def known_target(self, record, target_dir):
        if not isinstance(record, dict):
            return None
        name = record.get("name")
        if not isinstance(name, str) or Path(name).name != name or name.startswith(".") or "\\" in name or record.get("directory") != str(target_dir):
            raise ValueError("Invalid receipt routing")
        return target_dir / name

    def choose(self, target_dir, name):
        base = safe_name(name)
        candidate, index = base, 1
        while os.path.lexists(target_dir / candidate):
            candidate = f"{Path(base).stem}-{index}.md"
            index += 1
        return candidate

    def consume(self, source, original):
        if snapshot(source) != original:
            raise Deferred("Source changed after persistence; retained for reprocessing")
        with directory(source.parent) as parent:
            info = os.stat(source.name, dir_fd=parent, follow_symlinks=False)
            if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) != original[1]:
                raise Deferred("Source replaced before cleanup")
            os.unlink(source.name, dir_fd=parent)
            os.fsync(parent)

    def process(self, source: Path, dry_run=False, delay=1):
        source = source.expanduser().absolute()
        if not eligible(source):
            raise ValueError("Expected a visible, regular, non-symlink .md file")
        for key in ("vault", "quarantine", "log_dir"):
            protected = self.cfg[key].resolve()
            if source.resolve() == protected or protected in source.resolve().parents:
                raise ValueError(f"Source must not be inside {key}")
        original = stable_read(source, delay)
        data = original[0]
        try:
            meta = validate(data)
        except InvalidNote as exc:
            if not dry_run:
                with self.lock():
                    self.quarantine(source, original, str(exc))
                notify(self.cfg, "TCF note rejected", f"{source.name}: {exc}")
            raise
        target_dir = self.target(meta)
        receipt_name = self.receipt_name(data)
        if dry_run:
            record = self.receipt(receipt_name)
            target = self.known_target(record, target_dir)
            if target and self.matches(target, data):
                return f"Already imported: {target}"
            return f"Would import: {target_dir / self.choose(target_dir, source.name)}"
        with self.lock(), directory(self.receipts, create=True) as receipts:
            record = self.receipt(receipt_name)
            target = self.known_target(record, target_dir)
            duplicate = bool(target and self.matches(target, data))
            with directory(target_dir, create=True) as dest:
                if duplicate:
                    # A pending receipt plus matching published bytes recovers a crash.
                    fd = os.open(target.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dest)
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                    os.fsync(dest)
                else:
                    while True:
                        name = self.choose(target_dir, source.name)
                        record = dict(directory=str(target_dir), name=name, state="pending")
                        atomic_json(receipts, receipt_name, record)
                        try:
                            publish(dest, name, data)
                            target = target_dir / name
                            break
                        except FileExistsError:
                            continue
                record["state"] = "committed"
                atomic_json(receipts, receipt_name, record)
                self.consume(source, original)
        result = f"{'Already imported' if duplicate else 'Imported'}: {target}"
        LOG.info(result)
        notify(self.cfg, "TCF learning note", result)
        return result

    def quarantine(self, source, original, reason):
        target_dir = self.cfg["quarantine"]
        digest = hashlib.sha256(original[0]).hexdigest()
        base = Path(safe_name(source.name)).stem[:60] + "-" + digest
        with directory(target_dir, create=True) as dest:
            name, index = base + ".md", 1
            while os.path.lexists(target_dir / name) and not self.matches(target_dir / name, original[0]):
                name = f"{base}-{index}.md"
                index += 1
            diagnostic = json.dumps(dict(source=str(source), reason=reason)).encode()
            try:
                publish(dest, name + ".reason.json", diagnostic)
            except FileExistsError:
                # A prior attempt may have persisted its reason before interruption.
                existing, _ = snapshot(target_dir / (name + ".reason.json"))
                if json.loads(existing).get("reason") != reason:
                    raise ValueError("Conflicting quarantine diagnostic; source retained")
            if not self.matches(target_dir / name, original[0]):
                publish(dest, name, original[0])
            os.fsync(dest)
            self.consume(source, original)
        LOG.error("Rejected %s: %s", source, reason)
