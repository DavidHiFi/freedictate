"""Check GitHub Releases for a newer FreeDictate, download it, verify it, install it."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import REPO, __version__, paths
from .log import log

API = f"https://api.github.com/repos/{REPO}/releases?per_page=15"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_PREREL_RANK = {"alpha": 0, "a": 0, "beta": 1, "b": 1, "pre": 1, "preview": 1, "rc": 2, "c": 2}


@dataclass
class Release:
    version: str
    tag: str
    name: str
    notes: str
    url: str
    prerelease: bool
    assets: dict[str, str]   # file name -> download URL


def parse_version(v: str) -> tuple:
    """'v3.1.0-rc.1' -> (3, 1, 0, 2, 1); a final release sorts after its pre-releases."""
    m = re.match(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-.]?([a-z]+)\.?(\d+)?)?", v.strip().lower())
    if not m:
        return (0,)
    major, minor, patch = (int(x or 0) for x in m.group(1, 2, 3))
    if m.group(4):
        rank = _PREREL_RANK.get(m.group(4), 0)   # alpha < beta < rc, so rc.1 beats beta.2
        return (major, minor, patch, rank, int(m.group(5) or 0))
    return (major, minor, patch, 3, 0)


def newer(candidate: str, current: str = __version__) -> bool:
    return parse_version(candidate) > parse_version(current)


def _get(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers={"User-Agent": f"FreeDictate/{__version__}",
                                               "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout)


def latest(include_prereleases: bool = False) -> Release | None:
    with _get(API) as r:
        data = json.load(r)
    best: Release | None = None
    for rel in data:
        if rel.get("draft") or (rel.get("prerelease") and not include_prereleases):
            continue
        version = rel["tag_name"].lstrip("v")
        cand = Release(version, rel["tag_name"], rel.get("name") or rel["tag_name"], rel.get("body") or "",
                       rel["html_url"], bool(rel.get("prerelease")),
                       {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])})
        if best is None or parse_version(cand.version) > parse_version(best.version):
            best = cand
    return best


def check(include_prereleases: bool = False) -> Release | None:
    """The newest release if it is newer than this build, else None."""
    rel = latest(include_prereleases)
    if rel and newer(rel.version):
        return rel
    return None


def _asset(rel: Release, portable: bool) -> tuple[str, str]:
    for name, url in rel.assets.items():
        n = name.lower()
        if portable and n.endswith(".zip") and "portable" in n:
            return name, url
        if not portable and n.endswith(".exe") and "setup" in n:
            return name, url
    raise RuntimeError("This release has no download for your kind of install. Open the release page instead.")


def _expected_sha(rel: Release, name: str) -> str | None:
    url = next((u for n, u in rel.assets.items() if n.upper().startswith("SHA256SUMS")), None)
    if not url:
        return None
    with _get(url) as r:
        for line in r.read().decode("utf-8", "replace").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].lstrip("*") == name:
                return parts[0].lower()
    return None


def download(rel: Release, progress: Callable[[int, int], None] | None = None) -> Path:
    name, url = _asset(rel, paths.portable())
    # Read the checksum before fetching the file. A download nobody can verify
    # is never saved, let alone installed.
    want = _expected_sha(rel, name)
    if not want:
        raise RuntimeError("This release has no checksum for the download, so it wasn't fetched. "
                           "Open the release page instead.")
    target = Path(tempfile.gettempdir()) / "FreeDictate-update" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256()
    with _get(url, timeout=60) as r, open(target, "wb") as out:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while chunk := r.read(1 << 18):
            out.write(chunk)
            sha.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    if sha.hexdigest() != want:
        target.unlink(missing_ok=True)
        raise RuntimeError("The download didn't match its checksum, so it wasn't installed. Try again.")
    return target


def install(file: Path) -> None:
    """Start the installer (or the portable swap) and let the caller quit."""
    if file.suffix.lower() == ".exe":
        subprocess.Popen([str(file), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS",
                          "/UPDATE=1"], close_fds=True)
        return
    # Portable: a short PowerShell script waits for this process to exit, copies
    # the new files over the app folder (data\ and portable.txt untouched), and
    # starts FreeDictate again.
    app = paths.APP_DIR
    # Write as UTF-8 with BOM: Windows PowerShell 5.1 reads BOM-less scripts as
    # ANSI, which garbles non-ASCII paths (José, Désirée...). Single quotes in
    # paths are escaped by doubling; -LiteralPath then treats them literally.
    def q(s: Path) -> str:
        return "'" + str(s).replace("'", "''") + "'"
    script = Path(tempfile.gettempdir()) / "FreeDictate-update" / "apply-portable.ps1"
    script.write_text(f"""
$ErrorActionPreference = 'Stop'
$exe = Join-Path {q(app)} 'FreeDictate.exe'
try {{
    $p = Get-Process -Id {os.getpid()} -ErrorAction SilentlyContinue
    if ($p -and -not $p.WaitForExit(30000)) {{
        # Still shutting down: don't copy over a running exe, just make sure
        # the old app is back in front. The update can be retried later.
        Start-Process -FilePath $exe
        exit
    }}
    $stage = Join-Path $env:TEMP 'FreeDictate-update\\stage'
    Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
    Expand-Archive -LiteralPath {q(file)} -DestinationPath $stage -Force
    $src = Get-ChildItem $stage -Directory | Select-Object -First 1
    if (-not (Test-Path (Join-Path $src.FullName 'FreeDictate.exe'))) {{ $src = Get-Item $stage }}
    Get-ChildItem $src.FullName | Where-Object {{ $_.Name -notin @('data', 'portable.txt') }} |
        ForEach-Object {{ Copy-Item $_.FullName -Destination {q(app)} -Recurse -Force }}
}} finally {{
    if (-not (Get-Process -Name FreeDictate -ErrorAction SilentlyContinue)) {{
        Start-Process -FilePath $exe
    }}
}}
""", encoding="utf-8-sig")
    subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                      "-File", str(script)], creationflags=_NO_WINDOW, close_fds=True)
