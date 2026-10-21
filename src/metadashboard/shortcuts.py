"""Start menu and desktop shortcuts to the app's no-console launcher (metadashboard-gui.exe), Windows only."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

NAME = 'MetaDashboard'
GUI = 'metadashboard-gui'

# WScript.Shell makes the .lnk; the paths come in through the environment, so nothing needs quoting
PS_CREATE = r"""
$shell = New-Object -ComObject WScript.Shell
foreach ($path in $env:MD_LINKS -split ';') {
    $lnk = $shell.CreateShortcut($path)
    $lnk.TargetPath = $env:MD_TARGET
    $lnk.WorkingDirectory = $env:MD_WORKDIR
    $lnk.Description = 'Profit calendar for several MT5 accounts'
    $lnk.Save()
}
"""


def _folders():
    # the shell's known folders, also when Desktop is redirected (e.g. to OneDrive)
    out = subprocess.run(['powershell', '-NoProfile', '-Command',
                          "[Environment]::GetFolderPath('Programs'); [Environment]::GetFolderPath('Desktop')"],
                         capture_output=True, text=True, check=True).stdout.split('\n')
    return [Path(p.strip()) for p in out if p.strip()]


def links():
    return [folder / (NAME + '.lnk') for folder in _folders()]


def gui_exe():
    """The launcher installed next to the running script (uv tool bin dir or .venv\\Scripts), else on PATH."""
    here = Path(sys.argv[0]).resolve().parent / (GUI + '.exe')
    if here.exists():
        return here
    found = shutil.which(GUI)
    if not found:
        raise SystemExit('%s.exe not found: install with  uv tool install ...  first (see README).' % GUI)
    return Path(found)


def install(workdir):
    target = gui_exe()
    workdir.mkdir(parents=True, exist_ok=True)
    paths = links()
    env = dict(os.environ, MD_LINKS=';'.join(map(str, paths)), MD_TARGET=str(target), MD_WORKDIR=str(workdir))
    subprocess.run(['powershell', '-NoProfile', '-Command', PS_CREATE], env=env, check=True)
    for p in paths:
        print('shortcut', p, '->', target)


def remove():
    for p in links():
        if p.exists():
            p.unlink()
            print('removed', p)
