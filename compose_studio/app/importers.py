"""Bounded project archives and the Jotion release installer, without shell code."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import stat
import tarfile
import tempfile
import urllib.request
from urllib.parse import urlsplit
import zipfile

MAX_ARCHIVE = 12 * 1024 * 1024
MAX_EXPANDED = 32 * 1024 * 1024
MAX_FILES = 1500
VERSION = re.compile(r'\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?\Z')
COMPOSE_NAMES = ('compose.yaml', 'compose.yml', 'docker-compose.yaml', 'docker-compose.yml')


def safe_path(name):
    path = PurePosixPath(name)
    if not name or path.is_absolute() or '..' in path.parts or '\\' in name or '\x00' in name:
        raise ValueError('Archiv enthält einen ungültigen Dateipfad.')
    if any(part.startswith('.studio') or part in ('.git', 'node_modules') for part in path.parts):
        raise ValueError('Archiv enthält reservierte oder unnötige Projektverzeichnisse.')
    return Path(*path.parts)


def extract_archive(data, target):
    if len(data) > MAX_ARCHIVE:
        raise ValueError('Archiv ist größer als 12 MiB.')
    entries = []
    stream = io.BytesIO(data)
    if zipfile.is_zipfile(stream):
        with zipfile.ZipFile(stream) as archive:
            for item in archive.infolist():
                path = safe_path(item.filename)
                kind = (item.external_attr >> 16) & 0o170000
                if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise ValueError('Symlinks und Spezialdateien sind im Import nicht erlaubt.')
                entries.append((path, item.is_dir(), item.file_size, item))
            validate_entries(entries)
            for path, directory, _, item in entries:
                destination = target / path
                if directory:
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(archive.read(item))
            apply_permissions(entries, target)
    else:
        stream.seek(0)
        try:
            with tarfile.open(fileobj=stream, mode='r:*') as archive:
                total_size = 0
                for item in archive:
                    path = safe_path(item.name)
                    if not (item.isfile() or item.isdir()):
                        raise ValueError('Symlinks und Spezialdateien sind im Import nicht erlaubt.')
                    entries.append((path, item.isdir(), item.size, item))
                    total_size += item.size
                    if len(entries) > MAX_FILES or total_size > MAX_EXPANDED:
                        raise ValueError('Archiv enthält zu viele oder zu große Dateien.')
                validate_entries(entries)
                for path, directory, _, item in entries:
                    destination = target / path
                    if directory:
                        destination.mkdir(parents=True, exist_ok=True)
                    else:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        with archive.extractfile(item) as source:
                            destination.write_bytes(source.read())
                apply_permissions(entries, target)
        except tarfile.TarError as error:
            raise ValueError('Datei ist kein lesbares ZIP-/TAR-Archiv.') from error


def apply_permissions(entries, target):
    """Keep regular source permissions for COPY/RUN; never retain setuid bits."""
    directories = {}
    for path, directory, _, item in entries:
        for parent in path.parents:
            if str(parent) != '.':
                directories.setdefault(parent, 0o755)
        mode = ((item.external_attr >> 16) if isinstance(item, zipfile.ZipInfo) else item.mode) & 0o777
        mode = mode or (0o755 if directory else 0o644)
        if directory:
            directories[path] = mode
        else:
            os.chmod(target / path, mode)
    for path in sorted(directories, key=lambda p: len(p.parts), reverse=True):
        os.chmod(target / path, directories[path])


def validate_entries(entries):
    if len(entries) > MAX_FILES or sum(entry[2] for entry in entries) > MAX_EXPANDED:
        raise ValueError('Archiv enthält zu viele oder zu große Dateien (maximal 32 MiB entpackt).')
    seen = set()
    for path, directory, _, _ in entries:
        if not directory:
            if str(path) in seen or str(path) == '.':
                raise ValueError('Doppelte oder ungültige Datei im Archiv.')
            seen.add(str(path))


def install_archive(workspace, name, data, configure=None):
    workspace.check_available()
    if not workspace.lock.acquire(blocking=False):
        raise BlockingIOError('Ein Vorgang läuft. Bitte warten.')
    temporary = Path(tempfile.mkdtemp(prefix='.import-', dir=workspace.root.parent))
    try:
        workspace.check_available()
        destination = workspace.project(name, exists=False)
        if destination.exists():
            raise ValueError('Projektname existiert bereits. Vorhandene Projekte werden nicht überschrieben.')
        extract_archive(data, temporary)
        project = temporary
        while not any((project / filename).is_file() for filename in COMPOSE_NAMES):
            children = list(project.iterdir())
            if len(children) != 1 or not children[0].is_dir():
                raise ValueError('Keine eindeutige Compose-Datei im Archiv-Hauptverzeichnis gefunden.')
            project = children[0]
        candidates = [project / filename for filename in COMPOSE_NAMES if (project / filename).is_file()]
        if len(candidates) != 1:
            raise ValueError('Archiv muss genau eine Compose-Hauptdatei enthalten.')
        if candidates[0].name != 'compose.yaml':
            candidates[0].rename(project / 'compose.yaml')
        if not (project / '.env').exists():
            example = project / '.env.example'
            workspace.write(project / '.env', example.read_text() if example.exists() else '')
        if configure:
            configure(project)
        os.replace(project, destination)
        return workspace.read(name)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
        workspace.lock.release()


def fetch(url, limit):
    request = urllib.request.Request(url, headers={'User-Agent': 'HA-Compose-Studio/0.2'})
    with urllib.request.urlopen(request, timeout=40) as response:
        content = response.read(limit + 1)
    if len(content) > limit:
        raise ValueError('Download ist zu groß.')
    return content


def install_jotion(workspace, name, version, public_url, port):
    if not isinstance(version, str) or (version and not VERSION.fullmatch(version)):
        raise ValueError('Version als 1.0.1 angeben oder für das neueste Release leer lassen.')
    parsed = urlsplit(public_url)
    if re.search(r'\s', public_url) or parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Gültige öffentliche HTTP(S)-Adresse ohne Zugangsdaten angeben.')
    if parsed.path not in ('', '/'):
        raise ValueError('Jotion benötigt eine eigene Adresse ohne Unterpfad.')
    if not isinstance(port, int) or isinstance(port, bool) or not 1024 <= port <= 65535:
        raise ValueError('Host-Port zwischen 1024 und 65535 angeben.')
    release_url = 'https://api.github.com/repos/xwumps/jotion/releases/' + ('tags/v' + version if version else 'latest')
    release = json.loads(fetch(release_url, 1024 * 1024))
    version = release['tag_name'].removeprefix('v')
    if not VERSION.fullmatch(version):
        raise ValueError('Ungültige Release-Version.')
    asset_name = 'jotion-' + version + '.tar.gz'
    assets = [a for a in release.get('assets', []) if a['name'] == asset_name]
    if len(assets) != 1:
        raise ValueError('Release enthält kein eindeutiges Jotion-Installationspaket.')
    url = 'https://github.com/xwumps/jotion/releases/download/v' + version + '/' + asset_name
    data = fetch(url, MAX_ARCHIVE)
    digest = assets[0].get('digest')
    if digest and digest != 'sha256:' + hashlib.sha256(data).hexdigest():
        raise ValueError('Prüfsumme des Release-Pakets stimmt nicht.')
    def configure(project):
        compose = (project / 'compose.yaml').read_text()
        compose = compose.replace("      - '${JOTION_HTTPS_PORT:-8443}:443'\n", '')
        workspace.write(project / 'compose.yaml', compose)
        values = dict(POSTGRES_PASSWORD=secrets.token_hex(24), REDIS_PASSWORD=secrets.token_hex(24),
                      JOTION_MASTER_KEY=base64.b64encode(secrets.token_bytes(32)).decode(),
                      AUTH_SECRET=base64.b64encode(secrets.token_bytes(32)).decode(),
                      JOTION_IMAGE_PREFIX='ghcr.io/xwumps/jotion', JOTION_VERSION=version,
                      JOTION_HTTP_PORT=str(port), JOTION_HTTPS_PORT='0',
                      JOTION_PUBLIC_URL=public_url.rstrip('/'), JOTION_SITE_ADDRESS=':80')
        values['DATABASE_URL'] = f"postgresql://jotion:{values['POSTGRES_PASSWORD']}@localhost:5432/jotion"
        values['REDIS_URL'] = f"redis://:{values['REDIS_PASSWORD']}@localhost:6379"
        lines = (project / '.env').read_text().splitlines()
        lines = [line for line in lines if line.split('=', 1)[0] not in values]
        lines.extend(key + '=' + value for key, value in values.items())
        workspace.write(project / '.env', '\n'.join(lines) + '\n')
    return install_archive(workspace, name, data, configure)
