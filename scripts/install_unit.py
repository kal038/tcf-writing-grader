"""Render a user unit, safely quoting systemd command-line values."""
import os
from pathlib import Path
import sys


def quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%').replace('$', '$$') + '"'


def main():
    project = Path(sys.argv[1]).resolve()
    if any(c in str(project) for c in '\n\r\x00'):
        raise SystemExit('Unsupported project path')
    unit = (project / 'systemd/tcf-importer.service.in').read_text()
    unit = unit.replace('@EXECUTABLE@', quote(project / '.venv/bin/tcf-importer'))
    unit = unit.replace('@CONFIG@', quote(Path.home() / '.config/tcf-importer/config.toml'))
    target = Path.home() / '.config/systemd/user/tcf-importer.service'
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(unit)
    os.replace(temporary, target)
    print(f'Installed {target}')


if __name__ == '__main__':
    main()
