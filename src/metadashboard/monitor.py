"""Setting up the monitoring terminal without manual steps (Windows).

create() copies an installed MetaTrader 5 into its own folder, with the broker servers the installed terminal
knows (config\\servers.dat) but never its saved logins (config\\accounts.dat). The copy always runs /portable, so
it keeps its data in its own folder. accounts() lists every account that has logged in to it
(bases\\<server>\\trades\\<login>); with "Save password" ticked at that login, the terminal logs in again by itself,
so MetaDashboard needs neither the account list nor the passwords.
"""
import os
import re
import shutil
from pathlib import Path

# not needed to monitor, or data of the source terminal (accounts, history, logs)
SKIP = {'bases', 'logs', 'mql5', 'tester', 'metaeditor64.exe', 'metatester64.exe', 'uninstall.exe'}
SKIP_CONFIG = {'accounts.dat'}  # the source terminal's saved logins, possibly trading passwords: never copied


def installed_terminals(exclude=None):
    """terminal64.exe of every MetaTrader 5 installed in Program Files (also broker-branded ones)."""
    found = []
    for base in {os.environ.get(k) for k in ('ProgramW6432', 'ProgramFiles', 'ProgramFiles(x86)')} - {None}:
        try:
            dirs = list(Path(base).iterdir())
        except OSError:
            continue
        found += [d / 'terminal64.exe' for d in dirs if (d / 'terminal64.exe').is_file()]
    found = sorted(set(found), key=lambda p: (p.parent.name != 'MetaTrader 5', str(p).lower()))
    return [p for p in found if not exclude or p.parent != Path(exclude).parent]


def _servers_file(install_dir):
    """The newest servers.dat of this installation: in its data folder (%APPDATA%\\MetaQuotes\\Terminal\\<id>),
    where a normal installation keeps it, or in the installation itself."""
    candidates = [install_dir / 'Config' / 'servers.dat']
    terminals = Path(os.environ.get('APPDATA', '')) / 'MetaQuotes' / 'Terminal'
    for origin in terminals.glob('*/origin.txt'):
        try:
            raw = origin.read_bytes()
            path = raw.decode('utf-16' if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else 'utf-8').strip()
        except (OSError, UnicodeDecodeError):
            continue
        if os.path.normcase(path.rstrip('\\')) == os.path.normcase(str(install_dir)):
            candidates.append(origin.parent / 'config' / 'servers.dat')
    candidates = [c for c in candidates if c.is_file()]
    return max(candidates, key=lambda c: c.stat().st_mtime) if candidates else None


def create(source_exe, dest, log=print):
    """Copy the MetaTrader 5 of source_exe to dest; returns dest\\terminal64.exe."""
    src = Path(source_exe).parent
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        name = item.name.lower()
        if name in SKIP:
            continue
        if item.is_dir():
            ignore = (lambda d, names: [n for n in names if n.lower() in SKIP_CONFIG]) if name == 'config' else None
            shutil.copytree(item, dest / item.name, ignore=ignore, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dest / item.name)
    servers = _servers_file(src)
    if servers:
        (dest / 'config').mkdir(exist_ok=True)
        shutil.copy2(servers, dest / 'config' / 'servers.dat')
        log('broker servers copied from %s' % servers)
    return dest / 'terminal64.exe'


def accounts(terminal_exe):
    """(login, server) of every account that has logged in to this (portable) terminal."""
    found = set()
    for d in (Path(terminal_exe).parent / 'bases').glob('*/trades/*'):
        if d.is_dir() and d.name.isdigit() and int(d.name) > 0:
            found.add((int(d.name), d.parent.parent.name))
    return sorted(found, key=lambda a: (a[1].lower(), a[0]))


def broker(server):
    """'VantageInternational-Live 3' -> 'VantageInternational'"""
    return re.split(r'[-_\s]', server)[0] or server
