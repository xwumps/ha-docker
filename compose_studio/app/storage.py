"""Persistent Compose storage and a lock shared with Supervisor backup hooks."""
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time


class OperationLock:
    def __init__(self, path):
        self.path = path
        self.local = threading.Lock()
        self.fd = None

    def acquire(self, blocking=True, timeout=-1):
        if not self.local.acquire(blocking, timeout):
            return False
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        deadline = None if timeout < 0 else time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.fd = fd
                return True
            except BlockingIOError:
                if not blocking or (deadline is not None and time.monotonic() >= deadline):
                    os.close(fd)
                    self.local.release()
                    return False
                time.sleep(0.05)

    def release(self):
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        os.close(self.fd)
        self.fd = None
        self.local.release()


def checked(workspace, args, timeout=600):
    result = workspace.run(args, timeout=timeout)
    if result['code']:
        raise ValueError(result['output'] or 'Docker-Vorgang fehlgeschlagen.')
    return result['output']


def containers(workspace, project=None):
    projects = ['cs_' + name for name in workspace.list_projects()] if project is None else ['cs_' + project]
    found = []
    for name in projects:
        ids = checked(workspace, ['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=' + name], 30).split()
        for ident in ids:
            raw = checked(workspace, ['docker', 'inspect', '--format',
                '{"id":{{json .Id}},"running":{{json .State.Running}},"mounts":{{json .Mounts}},"labels":{{json .Config.Labels}}}', ident], 30)
            found.append(json.loads(raw))
    return found


def legacy_volumes(workspace, name):
    return checked(workspace, ['docker', 'volume', 'ls', '-q', '--filter',
        'label=com.docker.compose.project=cs_' + name], 30).split()


def inside(path, root):
    return Path(path).resolve().is_relative_to(root.resolve())


def wrapper_name(project, key, directory):
    digest = hashlib.sha256(str(directory).encode()).hexdigest()[:16]
    return f'cs_{project}_data_{digest}'


def own_image(workspace):
    ids = checked(workspace, ['docker', 'ps', '-q'], 30).split()
    import socket
    rows = checked(workspace, ['docker', 'inspect', '--format', '{{.Config.Hostname}} {{.Image}}', *ids], 30)
    images = [line.split()[1] for line in rows.splitlines() if line.split()[0] == socket.gethostname()]
    if len(images) != 1:
        raise ValueError('Eigenes Hilfs-Image nicht eindeutig gefunden.')
    return images[0]


def copy_legacy_volume(workspace, old_name, destination):
    """Copy while services are stopped; retain the original volume unchanged."""
    probe = workspace.run(['docker', 'volume', 'inspect', old_name], timeout=30)
    if probe['code']:
        if 'no such volume' in probe['output'].lower():
            return False
        raise ValueError(probe['output'])
    volume = json.loads(probe['output'])[0]
    if volume.get('Driver') != 'local' or volume.get('Options'):
        raise ValueError(f'Volume {old_name}: nur normale lokale Volumes werden automatisch übernommen.')
    users = checked(workspace, ['docker', 'ps', '-q', '--filter', 'volume=' + old_name], 30).split()
    if users:
        raise ValueError(f'Volume {old_name} wird noch von laufenden Containern verwendet.')
    temporary = Path(tempfile.mkdtemp(prefix='.migrate-', dir=destination.parent))
    try:
        checked(workspace, ['docker', 'run', '--rm', '--network', 'none',
            '--mount', f'type=volume,src={old_name},dst=/from,readonly',
            '--mount', f'type=bind,src={temporary},dst=/to',
            '--entrypoint', 'python3', own_image(workspace), '/app/volume_helper.py'], 600)
        destination.rmdir()
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return True


def prepare(workspace, name):
    """Compile an image-only deployment with all local volume data below /data."""
    original = workspace.command(name, 'config', '--format', 'json', runtime=False)
    config = json.loads(checked(workspace, original, 30))
    config = copy.deepcopy(config)
    root = workspace.root.parent
    project = workspace.project(name)
    for section in ('configs', 'secrets'):
        for item in config.get(section, {}).values():
            if item.get('external') or (item.get('file') and not inside(item['file'], root)):
                raise ValueError('Konfigurationen und Secrets müssen im App-Datenordner liegen.')
    for service in config.get('services', {}).values():
        if not service.get('image'):
            raise ValueError('Jeder Dienst benötigt ein fertiges image:. Quellcode-Builds werden nicht ausgeführt.')
        service.pop('build', None)
        if service.get('volumes_from'):
            raise ValueError('volumes_from kann nicht automatisch mitgesichert werden.')
        for mount in service.get('volumes', []):
            if mount['type'] == 'bind' and not inside(mount['source'], root):
                raise ValueError('Bind-Mounts müssen innerhalb des App-Datenordners liegen. Relative Projektpfade verwenden.')
            if mount['type'] == 'volume' and not mount.get('source'):
                raise ValueError('Anonyme Volumes werden nicht unterstützt. Benanntes Volume verwenden.')
        for filename in ('env_file', 'label_file'):
            for item in service.get(filename, []):
                path = item.get('path') if isinstance(item, dict) else item
                if not inside(path, root):
                    raise ValueError('Zusatzdateien müssen im App-Datenordner liegen.')
    migration = project / '.studio-volumes.json'
    runtime = project / '.studio-runtime.json'
    previous_config = json.loads(runtime.read_text()) if runtime.exists() else {}
    initialized = previous_config.get('x-studio-volume-origins',
        json.loads(migration.read_text()) if migration.exists() else {})
    known_sources = {v.get('name', f'cs_{name}_{key}') for key, v in config.get('volumes', {}).items()}
    known_sources.update(v['name'] for v in previous_config.get('volumes', {}).values())
    known_sources.update(v['original'] for v in initialized.values() if v['original'])
    for container in containers(workspace, name):
        if any(mount['Type'] == 'volume' and mount['Name'] not in known_sources for mount in container['mounts']):
            raise ValueError('Bestehendes anonymes oder nicht zugeordnetes Volume: Ziel zuerst explizit im YAML benennen.')
    for volume in config.get('volumes', {}).values():
        if volume.get('external') or volume.get('driver', 'local') != 'local' or volume.get('driver_opts'):
            raise ValueError('Externe Volumes, eigene Treiber und driver_opts sind nicht automatisch sicherbar.')
    pending = []
    try:
        for key, volume in config.get('volumes', {}).items():
            directory = root / 'storage' / name / hashlib.sha256(key.encode()).hexdigest()[:20]
            directory.mkdir(parents=True, exist_ok=True)
            if key not in initialized:
                old_name = volume.get('name', f'cs_{name}_{key}')
                if any(directory.iterdir()):
                    raise ValueError(f'Datenordner für {key} ist unerwartet belegt; automatische Übernahme abgebrochen.')
                pending.append(directory)
                copied = copy_legacy_volume(workspace, old_name, directory)
                initialized[key] = {'original': old_name if copied else None}
            volume.clear()
            volume.update(name=wrapper_name(name, key, directory), driver='local',
                          driver_opts={'type': 'none', 'o': 'bind', 'device': str(directory)})
        # One atomic commit contains both the deployment and migration state.
        config['x-studio-volume-origins'] = initialized
        config['x-studio-root'] = str(root)
        workspace.write(runtime, json.dumps(config))
    except Exception:
        for directory in pending:
            shutil.rmtree(directory, ignore_errors=True)
        raise
    return config


def audit(workspace, name):
    project = workspace.project(name)
    runtime = project / '.studio-runtime.json'
    if not runtime.exists():
        return
    config = json.loads(runtime.read_text())
    supported = {v['name'] for v in config.get('volumes', {}).values()}
    migrated = project / '.studio-volumes.json'
    origins = config.get('x-studio-volume-origins', json.loads(migrated.read_text()) if migrated.exists() else {})
    supported.update(v['original'] for v in origins.values() if v['original'])
    for container in containers(workspace, name):
        for mount in container['mounts']:
            if mount['Type'] == 'volume' and mount['Name'] not in supported:
                raise ValueError('Ein Image legt ein anonymes Volume an. Dieses Ziel im YAML explizit als benanntes Volume eintragen.')


def rebase(workspace, name):
    """Regenerate host paths after restoring the app on another HA host/slug."""
    project = workspace.project(name)
    runtime = project / '.studio-runtime.json'
    if not runtime.exists():
        return prepare(workspace, name)
    config = json.loads(runtime.read_text())
    previous = Path(config.get('x-studio-root') or (project / '.studio-root').read_text())
    current = workspace.root.parent
    def translate(value):
        path = Path(value)
        return str(current / path.relative_to(previous)) if path.is_relative_to(previous) else value
    for key, volume in config.get('volumes', {}).items():
        device = volume['driver_opts']['device']
        volume['driver_opts']['device'] = translate(device)
        volume['name'] = wrapper_name(name, key, volume['driver_opts']['device'])
        Path(volume['driver_opts']['device']).mkdir(parents=True, exist_ok=True)
    for section in ('configs', 'secrets'):
        for item in config.get(section, {}).values():
            if item.get('file'):
                item['file'] = translate(item['file'])
    for service in config.get('services', {}).values():
        for mount in service.get('volumes', []):
            if mount['type'] == 'bind':
                mount['source'] = translate(mount['source'])
    config['x-studio-root'] = str(current)
    workspace.write(runtime, json.dumps(config))
    return config
