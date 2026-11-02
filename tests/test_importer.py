import json
import os
from pathlib import Path
import subprocess
from unittest.mock import patch

import pytest

from tcf_importer import core
from tcf_importer.cli import main, scan, InboxEvents

SAMPLE = Path(__file__).parents[1] / 'examples/2026-11-02-task-1-invitation.md'


@pytest.fixture
def data():
    return SAMPLE.read_bytes()


@pytest.fixture
def cfg(tmp_path):
    result = core.DEFAULTS | {key: tmp_path / key for key in ('inbox', 'vault', 'quarantine', 'log_dir')}
    result['notifications'] = False
    for key in ('inbox', 'vault'):
        result[key].mkdir()
    return result


def source(cfg, data, name='lesson.md'):
    path = cfg['inbox'] / name
    path.write_bytes(data)
    return path


def notes(cfg):
    return list(cfg['vault'].rglob('*.md'))


@pytest.mark.parametrize('task', [1, 2, 3])
def test_valid_import(cfg, data, task):
    data = data.replace(b'task: 1', f'task: {task}'.encode())
    path = source(cfg, data)
    core.Importer(cfg).process(path, delay=0)
    assert not path.exists()
    assert notes(cfg)[0].read_bytes() == data
    assert notes(cfg)[0].parent.name == f'Task-{task}'


@pytest.mark.parametrize('old,new', [
    (b'task: 1', b'task: 4'), (b'task: 1', b'task: true'),
    (b'schema_version: 1', b'schema_version: 2'),
    (b'schema_version: 1', b'schema_version: true'),
    (b'topic: invitation-au-restaurant', b'topic: ../../escape'),
    (b'level: B2', b'level: A1'), (b'date: 2026-11-02', b'date: 2026-02-30'),
    (b'tags:', b'tags: [unterminated'),
    (b'task: 1', b'task: 1\ntask: 2'),
    (b'task: 1', b'task: !!python/object:os.system {}'),
    (b'## Reusable Grammar', b'## Other Grammar'),
])
def test_invalid_quarantined(cfg, data, old, new):
    path = source(cfg, data.replace(old, new))
    with pytest.raises(core.InvalidNote):
        core.Importer(cfg).process(path, delay=0)
    assert not path.exists()
    assert not notes(cfg)
    assert list(cfg['quarantine'].glob('*.reason.json'))


def test_missing_empty_and_fenced_sections(data):
    with pytest.raises(core.InvalidNote):
        core.validate(b'```\n' + data + b'\n```')
    with pytest.raises(core.InvalidNote):
        core.validate(data.replace(b'## Reusable Grammar', b'```\n## Reusable Grammar').replace(b'## Notable Personal Mistakes', b'```\n## Notable Personal Mistakes'))
    with pytest.raises(core.InvalidNote):
        core.validate(data.replace('Use the conditional to make a polite suggestion: « On pourrait dîner ensemble. »'.encode(), b''))


def test_duplicate_names_and_contents(cfg, data):
    importer = core.Importer(cfg)
    importer.process(source(cfg, data), delay=0)
    importer.process(source(cfg, data + b'\nAnother exercise.'), delay=0)
    assert {p.name for p in notes(cfg)} == {'lesson.md', 'lesson-1.md'}
    assert 'Already imported' in importer.process(source(cfg, data, 'renamed.md'), delay=0)
    assert len(notes(cfg)) == 2


def test_symlink_source_and_routing(cfg, data, tmp_path):
    real = tmp_path / 'real.md'
    real.write_bytes(data)
    link = cfg['inbox'] / 'link.md'
    link.symlink_to(real)
    assert not core.eligible(link)
    with pytest.raises(ValueError):
        core.Importer(cfg).process(link, delay=0)
    (cfg['vault'] / 'TCF Canada').symlink_to(tmp_path, target_is_directory=True)
    path = source(cfg, data)
    with pytest.raises(OSError):
        core.Importer(cfg).process(path, delay=0)
    assert path.exists()
    assert real.read_bytes() == data


def test_safe_filename(cfg, data):
    core.Importer(cfg).process(source(cfg, data, 'evil\\name.md'), delay=0)
    assert notes(cfg)[0].name == 'evil_name.md'


def test_interrupted_write_retained(cfg, data):
    path = source(cfg, data)
    with patch.object(core.time, 'sleep', side_effect=lambda _: path.write_bytes(path.read_bytes() + b' ')):
        with pytest.raises(core.Deferred):
            core.Importer(cfg).process(path)
    assert path.exists()
    assert not notes(cfg)


@pytest.mark.parametrize('phase', ['publication', 'commit', 'cleanup'])
def test_restart_recovery(cfg, data, phase):
    path = source(cfg, data)
    importer = core.Importer(cfg)
    original_publish = core.publish
    original_json = core.atomic_json
    def interrupted_publish(parent, name, value):
        original_publish(parent, name, value)
        if name.endswith('.md'):
            raise OSError('crash after publication')
    def interrupted_json(parent, name, value):
        if value.get('state') == 'committed':
            raise OSError('crash before receipt commit')
        return original_json(parent, name, value)
    context = {'publication': patch.object(core, 'publish', side_effect=interrupted_publish),
               'commit': patch.object(core, 'atomic_json', side_effect=interrupted_json),
               'cleanup': patch.object(importer, 'consume', side_effect=OSError('crash before deletion'))}[phase]
    with context, pytest.raises(OSError):
        importer.process(path, delay=0)
    assert path.exists()
    assert len(notes(cfg)) == 1
    assert scan(cfg['inbox']) == [path]
    core.Importer(cfg).process(path, delay=0)
    assert not path.exists()
    assert len(notes(cfg)) == 1


def test_persistence_failure_retains_source(cfg, data):
    path = source(cfg, data)
    with patch.object(core.os, 'fsync', side_effect=OSError('disk error')):
        with pytest.raises(OSError):
            core.Importer(cfg).process(path, delay=0)
    assert path.exists()


def test_changed_source_after_publication(cfg, data):
    path = source(cfg, data)
    publish = core.publish
    def change(parent, name, value):
        publish(parent, name, value)
        if name.endswith('.md'):
            path.write_bytes(data + b'\nNew revision')
    with patch.object(core, 'publish', side_effect=change), pytest.raises(core.Deferred):
        core.Importer(cfg).process(path, delay=0)
    assert path.exists()
    assert notes(cfg)[0].read_bytes() == data


def test_cross_filesystem_algorithm(cfg, data):
    path = source(cfg, data)
    link = core.os.link
    def local_link(src, dst, **kwargs):
        assert kwargs['src_dir_fd'] == kwargs['dst_dir_fd']
        return link(src, dst, **kwargs)
    with patch.object(core.os, 'rename', side_effect=OSError('EXDEV')), patch.object(core.os, 'link', side_effect=local_link):
        core.Importer(cfg).process(path, delay=0)
    assert notes(cfg)[0].read_bytes() == data


def test_actual_cross_filesystem(cfg, data):
    import tempfile
    root = Path('/dev/shm')
    if not root.is_dir() or root.stat().st_dev == cfg['inbox'].stat().st_dev:
        pytest.skip('No second filesystem available')
    with tempfile.TemporaryDirectory(dir=root, prefix='tcf-test-') as temporary:
        cfg['vault'] = Path(temporary)
        core.Importer(cfg).process(source(cfg, data), delay=0)
        assert notes(cfg)[0].read_bytes() == data


def test_notification_failure_is_success(cfg, data):
    cfg['notifications'] = True
    with patch.object(core.subprocess, 'run', side_effect=FileNotFoundError):
        core.Importer(cfg).process(source(cfg, data), delay=0)
    assert len(notes(cfg)) == 1


def test_dry_run_does_not_write(cfg, data):
    path = source(cfg, data)
    assert 'Would import' in core.Importer(cfg).process(path, dry_run=True, delay=0)
    assert path.exists()
    assert not cfg['log_dir'].exists()
    assert not notes(cfg)


def test_scan_filters(cfg, data):
    good = source(cfg, data)
    for name in ('.hidden.md', 'note.tmp.md', 'note.part.md', 'note.txt'):
        source(cfg, data, name)
    (cfg['inbox'] / 'link.md').symlink_to(good)
    assert scan(cfg['inbox']) == [good]


def test_cli_validate(data, tmp_path, capsys):
    path = tmp_path / 'note.md'
    path.write_bytes(data)
    assert main(['validate', str(path)]) == 0
    path.write_text('bad')
    assert main(['validate', str(path)]) == 1


def test_config_overlap_and_types(cfg, tmp_path):
    path = tmp_path / 'config.toml'
    def write(values):
        path.write_text('\n'.join(f'{k} = {json.dumps(str(v) if isinstance(v, Path) else v)}' for k, v in values.items()))
    write(cfg)
    assert core.load_config(path)['vault'] == cfg['vault']
    write(cfg | {'quarantine': cfg['inbox'] / 'rejected'})
    with pytest.raises(ValueError, match='overlap'):
        core.load_config(path)
    write(cfg | {'poll_interval_seconds': 0})
    with pytest.raises(ValueError, match='positive'):
        core.load_config(path)


def test_events_wake_reconciliation():
    import threading
    from watchdog.events import FileCreatedEvent, FileOpenedEvent
    wake = threading.Event()
    handler = InboxEvents(wake)
    handler.on_any_event(FileOpenedEvent('note.md'))
    assert not wake.is_set()
    handler.on_any_event(FileCreatedEvent('note.md'))
    assert wake.is_set()


def test_install_script_never_enables_or_starts():
    script = (SAMPLE.parents[1] / 'scripts/install.sh').read_text()
    assert 'systemctl --user daemon-reload' in script
    assert 'systemctl --user enable' not in script
    assert 'systemctl --user start' not in script


def test_quarantine_restart(cfg):
    path = source(cfg, b'not a note')
    importer = core.Importer(cfg)
    with patch.object(importer, 'consume', side_effect=OSError('interrupted cleanup')):
        with pytest.raises(OSError):
            importer.process(path, delay=0)
    with pytest.raises(core.InvalidNote):
        core.Importer(cfg).process(path, delay=0)
    assert len(list(cfg['quarantine'].glob('*.md'))) == 1
    assert not path.exists()


def test_vault_source_refused(cfg, data):
    path = cfg['vault'] / 'keep.md'
    path.write_bytes(data)
    with pytest.raises(ValueError, match='inside vault'):
        core.Importer(cfg).process(path, delay=0)
    assert path.exists()


def test_setup_existing_vault_only(tmp_path, monkeypatch):
    from tcf_importer.cli import setup
    config = tmp_path / 'settings.toml'
    monkeypatch.setattr('builtins.input', lambda _: str(tmp_path / 'absent'))
    with pytest.raises(ValueError, match='already exist'):
        setup(config)
    assert not config.exists()
    monkeypatch.setattr('builtins.input', lambda _: '')
    with pytest.raises(ValueError, match='required'):
        setup(config)


def test_lock_serializes_processes(cfg):
    import sys
    import time
    importer = core.Importer(cfg)
    code = 'import fcntl,sys; f=open(sys.argv[1], "r+"); fcntl.flock(f, fcntl.LOCK_EX); print("locked", flush=True)'
    with importer.lock():
        child = subprocess.Popen([sys.executable, '-c', code, str(cfg['log_dir'] / 'import.lock')], stdout=subprocess.PIPE, text=True)
        try:
            time.sleep(0.1)
            assert child.poll() is None
        except BaseException:
            child.kill()
            child.wait()
            raise
    assert child.communicate(timeout=5)[0].strip() == 'locked'


def test_watcher_startup_and_periodic_recovery(cfg, data, tmp_path):
    """Disable event delivery: startup and periodic scanning must still import."""
    import sys
    import time
    cfg['poll_interval_seconds'] = 0.1
    config = tmp_path / 'watch.toml'
    config.write_text('\n'.join(f'{k} = {json.dumps(str(v) if isinstance(v, Path) else v)}' for k, v in cfg.items()))
    source(cfg, data, 'startup.md')
    code = '''from tcf_importer import cli
cli.InboxEvents.on_any_event = lambda *args: None
raise SystemExit(cli.main())
'''
    child = subprocess.Popen([sys.executable, '-c', code, '--config', str(config), 'watch'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    def await_count(count):
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if len(notes(cfg)) == count and not scan(cfg['inbox']):
                return
            assert child.poll() is None
            time.sleep(0.05)
        pytest.fail('Watcher failed to reconcile')
    try:
        await_count(1)
        source(cfg, data + b'\nSecond attempt', 'missed.md')
        await_count(2)
    finally:
        child.terminate()
        try:
            child.communicate(timeout=6)
        except subprocess.TimeoutExpired:
            child.kill()
            child.communicate()
    assert child.returncode == 0


def test_install_script_with_mock_tools(tmp_path):
    import shutil
    root = tmp_path / 'project with spaces'
    (root / 'scripts').mkdir(parents=True)
    (root / '.venv/bin').mkdir(parents=True)
    shutil.copy(SAMPLE.parents[1] / 'scripts/install.sh', root / 'scripts/install.sh')
    binary = tmp_path / 'bin'
    binary.mkdir()
    log = tmp_path / 'calls'
    for name in ('python3', 'systemctl'):
        executable = binary / name
        executable.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$TEST_CALL_LOG"\n')
        executable.chmod(0o755)
    shutil.copy(binary / 'python3', root / '.venv/bin/python')
    subprocess.run(['bash', str(root / 'scripts/install.sh')], check=True,
                   env=os.environ | {'PATH': str(binary) + ':' + os.environ['PATH'], 'TEST_CALL_LOG': str(log)}, capture_output=True)
    calls = log.read_text()
    assert '--user daemon-reload' in calls
    assert 'enable' not in calls and 'start' not in calls
