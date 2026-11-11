"""Native Docker containers and Dockerfile builds; no Compose conversion."""
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import stat
import tempfile

from importers import extract_archive, safe_path
from storage import checked, inside

NAME = re.compile(r'[a-z][a-z0-9_-]{0,39}\Z')
MANAGED = 'io.ha-docker.managed'
OWNER = 'io.ha-docker.name'
FINGERPRINT = 'io.ha-docker.fingerprint'
SOCKETS = {'/var/run/docker.sock', '/run/docker.sock'}
DEFAULTS = dict(image='', command=[], entrypoint='', env={}, ports=[], mounts=[],
    restart='unless-stopped', network='bridge', user='', workdir='', hostname='',
    memory='', cpus='', read_only=False, privileged=False, init=False, cap_add=[], cap_drop=[],
    devices=[], add_hosts=[], dns=[], tmpfs=[], labels={}, build=False,
    dockerfile='Dockerfile', build_args={}, target='', pull_policy='missing')


def words(value):
    if isinstance(value, str):
        if '\0' in value:
            raise ValueError('Befehl enthält ein ungültiges Nullzeichen.')
        return shlex.split(value)
    if isinstance(value, list) and all(isinstance(v, str) and '\0' not in v for v in value):
        return value
    raise ValueError('Befehl muss Text oder eine Liste von Argumenten sein.')


def text(value):
    if not isinstance(value, str) or '\0' in value or '\n' in value or '\r' in value:
        raise ValueError('Ungültiger Docker-Optionswert.')
    return value


def mount_parts(value, name):
    parts = text(value).split(':')
    if len(parts) == 1:
        source, target, mode = '_auto_' + name + '_' + hashlib.sha256(value.encode()).hexdigest()[:12], parts[0], 'rw'
    elif len(parts) in (2, 3):
        source, target = parts[:2]
        mode = parts[2] if len(parts) == 3 else 'rw'
    else:
        raise ValueError('Mount als daten:/container/pfad[:ro] angeben.')
    if not source or not target.startswith('/') or '..' in PurePosixPath(target).parts or mode not in ('ro', 'rw'):
        raise ValueError('Mount benötigt einen absoluten Containerpfad und optional ro/rw.')
    if source.startswith('/') and source not in SOCKETS:
        raise ValueError('Host-Datenpfade außerhalb der App sind nicht automatisch sicherbar. ./pfad oder einen Volumenamen verwenden.')
    if source.startswith('.'):
        safe_path(source)
    elif source not in SOCKETS and not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', source):
        raise ValueError('Ungültiger Volumename. Relative Bind-Pfade mit ./ beginnen.')
    return source, target, mode


def normalize(name, supplied):
    if not NAME.fullmatch(name or ''):
        raise ValueError('Name: mit a–z beginnen, maximal 40 Zeichen aus a–z, 0–9, _ und -.')
    if not isinstance(supplied, dict) or set(supplied) - set(DEFAULTS):
        raise ValueError('Unbekannte Docker-Konfigurationsfelder.')
    config = copy.deepcopy(DEFAULTS)
    config.update(supplied)
    for key in ('image', 'entrypoint', 'restart', 'network', 'user', 'workdir', 'hostname', 'memory', 'cpus', 'dockerfile', 'target', 'pull_policy'):
        text(config[key])
    for key in ('build', 'read_only', 'privileged', 'init'):
        if not isinstance(config[key], bool):
            raise ValueError(key + ' muss ein Schalter sein.')
    config['command'] = words(config['command'])
    for key in ('ports', 'mounts', 'cap_add', 'cap_drop', 'devices', 'add_hosts', 'dns', 'tmpfs'):
        if not isinstance(config[key], list) or len(config[key]) > 100:
            raise ValueError(key + ' muss eine Liste sein (maximal 100 Einträge).')
        for item in config[key]:
            text(item)
    for key in ('env', 'build_args', 'labels'):
        if not isinstance(config[key], dict) or len(config[key]) > 300:
            raise ValueError(key + ' muss eine Zuordnung sein.')
        for k, v in config[key].items():
            text(k)
            if not isinstance(v, str) or '\0' in v or '=' in k:
                raise ValueError('Ungültiger Schlüssel/Wert in ' + key)
            if key != 'labels' and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', k):
                raise ValueError('Ungültiger Variablenname: ' + k)
            if key == 'labels' and k.startswith(('io.ha-docker.', 'com.docker.compose.')):
                raise ValueError('Interne Verwaltungslabels dürfen nicht gesetzt werden.')
    for port in config['ports']:
        if not re.fullmatch(r'[0-9a-fA-F.:\[\]-]+(?:/(?:tcp|udp|sctp))?', port) or not any(c.isdigit() for c in port) or port.startswith('-'):
            raise ValueError('Port z. B. als 8090:80 oder 127.0.0.1:8090:80 angeben.')
    targets = []
    for mount in config['mounts']:
        targets.append(mount_parts(mount, name)[1])
    if len(set(targets)) != len(targets):
        raise ValueError('Jeder Container-Mountpfad darf nur einmal vorkommen.')
    if config['restart'] not in ('no', 'always', 'unless-stopped', 'on-failure') and not re.fullmatch(r'on-failure:\d+', config['restart']):
        raise ValueError('Ungültige Neustartregel.')
    if config['pull_policy'] not in ('missing', 'always', 'never'):
        raise ValueError('Ungültige Image-Laderegel.')
    if config['network'] == 'host' and config['ports']:
        raise ValueError('Bei Host-Netzwerk keine Port-Zuordnungen angeben.')
    if config['image'].startswith('-') or any(c.isspace() for c in config['image']):
        raise ValueError('Ungültiger Image-Name.')
    if config['build']:
        config['image'] = 'ha-docker/' + name + ':local'
        if str(safe_path(config['dockerfile'])) == '.':
            raise ValueError('Dockerfile-Pfad fehlt.')
    elif not config['image']:
        raise ValueError('Docker-Image fehlt.')
    for device in config['devices']:
        if not device.startswith('/dev/'):
            raise ValueError('Gerätepfade müssen mit /dev/ beginnen.')
    if len(json.dumps(config).encode()) > 256 * 1024:
        raise ValueError('Docker-Konfiguration ist größer als 256 KiB.')
    return config


def parse_run(command):
    """Parse a single docker run command, never evaluate host shell syntax."""
    if not isinstance(command, str):
        raise ValueError('docker run-Befehl als Text angeben.')
    args = shlex.split(command.replace('\\\r\n', '').replace('\\\n', ''))
    if args[:3] == ['docker', 'container', 'run']:
        args = ['docker', 'run', *args[3:]]
    if args[:2] != ['docker', 'run']:
        raise ValueError('Einen einzelnen docker run-Befehl ohne sudo einfügen.')
    if any(a in (';', '&&', '||', '|', '>', '>>', '<', '&') for a in args):
        raise ValueError('Shell-Verkettungen werden nicht ausgeführt. Nur docker run einfügen.')
    config, name = copy.deepcopy(DEFAULTS), 'docker-app'
    values = {'--name': 'name', '--publish': 'ports', '-p': 'ports', '--env': 'env', '-e': 'env',
        '--volume': 'mounts', '-v': 'mounts', '--mount': 'mount_spec', '--restart': 'restart',
        '--network': 'network', '--net': 'network', '--entrypoint': 'entrypoint', '--user': 'user', '-u': 'user',
        '--workdir': 'workdir', '-w': 'workdir', '--hostname': 'hostname', '-h': 'hostname',
        '--memory': 'memory', '-m': 'memory', '--cpus': 'cpus', '--cap-add': 'cap_add',
        '--cap-drop': 'cap_drop', '--device': 'devices', '--add-host': 'add_hosts', '--dns': 'dns',
        '--tmpfs': 'tmpfs', '--label': 'labels', '-l': 'labels', '--pull': 'pull_policy'}
    i = 2
    while i < len(args) and args[i].startswith('-'):
        option = args[i]
        if option == '--':
            i += 1
            break
        if option in ('-d', '--detach'):
            i += 1
            continue
        if option in ('--read-only', '--privileged', '--init'):
            config[option[2:].replace('-', '_')] = True
            i += 1
            continue
        attached = None
        if option.startswith('--') and '=' in option:
            option, attached = option.split('=', 1)
        elif len(option) > 2 and option[:2] in ('-p', '-e', '-v', '-u', '-w', '-h', '-m', '-l'):
            option, attached = option[:2], option[2:]
        if option not in values:
            raise ValueError('Docker-Option nicht unterstützt: ' + option + '. Keine Optionen werden stillschweigend entfernt.')
        if attached is None:
            i += 1
            if i >= len(args):
                raise ValueError('Wert fehlt für ' + option)
            attached = args[i]
        field = values[option]
        if field == 'name':
            name = attached
        elif field in ('env', 'labels'):
            if '=' not in attached:
                raise ValueError('Variable/Label mit explizitem WERT angeben: NAME=WERT.')
            k, v = attached.split('=', 1)
            config[field][k] = v
        elif field == 'mount_spec':
            spec = {}
            for part in attached.split(','):
                k, _, v = part.partition('=')
                spec[k] = v
            if set(spec) - {'type', 'source', 'src', 'target', 'dst', 'destination', 'readonly', 'ro'}:
                raise ValueError('Diese --mount-Unteroption wird nicht unterstützt.')
            source = spec.get('source', spec.get('src', ''))
            target = spec.get('target', spec.get('dst', spec.get('destination', '')))
            kind = spec.get('type', 'volume')
            if kind not in ('volume', 'bind') or (kind == 'bind' and not source):
                raise ValueError('--mount benötigt type=volume|bind und einen gültigen Pfad.')
            if kind == 'bind' and not source.startswith(('/', '.')):
                raise ValueError('Relative Bind-Pfade müssen mit ./ beginnen.')
            if kind == 'volume' and source and not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', source):
                raise ValueError('type=volume benötigt einen Volumenamen, keinen Host-Pfad.')
            mount = (source + ':' if source else '') + target
            readonly = spec.get('readonly', spec.get('ro'))
            if readonly not in (None, '', 'true', 'false', '1', '0'):
                raise ValueError('readonly muss true oder false sein.')
            if readonly in ('', 'true', '1'):
                if not source:
                    raise ValueError('Für ein schreibgeschütztes Volume einen Namen angeben.')
                mount += ':ro'
            config['mounts'].append(mount)
        elif isinstance(config[field], list):
            config[field].append(attached)
        else:
            config[field] = attached
        i += 1
    if i >= len(args):
        raise ValueError('Image fehlt im docker run-Befehl.')
    config['image'], config['command'] = args[i], args[i + 1:]
    return {'name': name, 'config': normalize(name, config)}


class Native:
    def __init__(self, workspace):
        self.w = workspace
        self.root = workspace.root.parent / 'containers'
        self.root.mkdir(parents=True, exist_ok=True)

    def folder(self, name, exists=True):
        if not isinstance(name, str) or not NAME.fullmatch(name):
            raise ValueError('Ungültiger Containername.')
        folder = self.root / name
        if folder.is_symlink():
            raise ValueError('Symlinks als Container-Projekt sind nicht erlaubt.')
        if exists and not (folder / '.studio-container.json').is_file():
            raise FileNotFoundError('Container-Konfiguration nicht gefunden.')
        return folder

    def names(self):
        return sorted(p.name for p in self.root.iterdir() if NAME.fullmatch(p.name) and not p.is_symlink() and (p / '.studio-container.json').is_file())

    def read(self, name):
        folder = self.folder(name)
        return {'name': name, 'config': json.loads((folder / '.studio-container.json').read_text()),
                'container_name': 'hd_' + name, 'host_path': str(folder),
                'context_path': str(folder / 'context'), 'files': self.files(name)}

    def files(self, name):
        folder = self.folder(name) / 'context'
        found = []
        for directory, dirs, files in os.walk(folder, followlinks=False):
            dirs[:] = [d for d in dirs if not (Path(directory) / d).is_symlink()]
            for filename in files:
                path = Path(directory) / filename
                if not path.is_symlink():
                    found.append(str(path.relative_to(folder)))
                    if len(found) == 300:
                        return sorted(found)
        return sorted(found)

    def save(self, name, config):
        config = normalize(name, config)
        self.w.check_available()
        if not self.w.lock.acquire(blocking=False):
            raise BlockingIOError('Ein Docker-/Compose-Vorgang läuft.')
        try:
            self.w.check_available()
            folder = self.folder(name, exists=False)
            (folder / 'context').mkdir(parents=True, exist_ok=True)
            self.w.write(folder / '.studio-container.json', json.dumps(config))
        finally:
            self.w.lock.release()
        return self.read(name)

    def upload(self, name, path, data, executable=None):
        self.w.check_available()
        relative = safe_path(path)
        if str(relative) == '.' or len(data) > 2 * 1024 * 1024:
            raise ValueError('Dateipfad fehlt oder Datei ist größer als 2 MiB.')
        if not self.w.lock.acquire(blocking=False):
            raise BlockingIOError('Ein Vorgang läuft.')
        try:
            self.w.check_available()
            root = self.folder(name) / 'context'
            destination = root / relative
            for parent in (destination, *destination.parents):
                if parent == root:
                    break
                if parent.is_symlink():
                    raise ValueError('Symlinks dürfen nicht überschrieben werden.')
            destination.parent.mkdir(parents=True, exist_ok=True)
            mode = stat.S_IMODE(destination.stat().st_mode) & 0o777 if destination.is_file() else 0o644
            if executable is not None:
                if not isinstance(executable, bool):
                    raise ValueError('Ausführbar muss ein Schalter sein.')
                mode = 0o755 if executable else 0o644
            fd, temporary = tempfile.mkstemp(prefix='.upload-', dir=destination.parent)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    os.fchmod(stream.fileno(), mode)
                    stream.write(data)
                os.replace(temporary, destination)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        finally:
            self.w.lock.release()
        return {'files': self.files(name)}

    def import_build(self, name, data, dockerfile='Dockerfile'):
        config = normalize(name, {'build': True, 'dockerfile': dockerfile})
        relative = safe_path(dockerfile)
        self.w.check_available()
        if not self.w.lock.acquire(blocking=False):
            raise BlockingIOError('Ein Vorgang läuft.')
        temporary = Path(tempfile.mkdtemp(prefix='.docker-import-', dir=self.root))
        try:
            self.w.check_available()
            folder = self.folder(name, exists=False)
            if folder.exists():
                raise ValueError('Containername existiert bereits.')
            extract_archive(data, temporary)
            context = temporary
            while not (context / relative).is_file():
                children = list(context.iterdir())
                if len(children) != 1 or not children[0].is_dir():
                    raise ValueError('Angegebener Dockerfile-Pfad ist im Archiv-Hauptverzeichnis nicht vorhanden.')
                context = children[0]
            folder.mkdir()
            try:
                os.replace(context, folder / 'context')
                self.w.write(folder / '.studio-container.json', json.dumps(config))
            except Exception:
                shutil.rmtree(folder)
                raise
        finally:
            shutil.rmtree(temporary, ignore_errors=True)
            self.w.lock.release()
        return self.read(name)

    def inspect(self, name, strict=True):
        self.folder(name)
        result = self.w.run(['docker', 'container', 'inspect', '--format',
            '{"id":{{json .Id}},"running":{{json .State.Running}},"state":{{json .State}},"mounts":{{json .Mounts}},"labels":{{json .Config.Labels}},"ports":{{json .NetworkSettings.Ports}}}', 'hd_' + name], timeout=30)
        if result['code']:
            if 'no such' in result['output'].lower():
                return None
            raise ValueError(result['output'])
        info = json.loads(result['output'])
        info['labels'] = info.get('labels') or {}
        if info['labels'].get(MANAGED) != 'true' or info['labels'].get(OWNER) != name:
            if not strict:
                return None
            raise ValueError('Namenskonflikt: Dieser Container gehört nicht zu dieser App.')
        info['name'] = name
        return info

    def containers(self):
        return [info for name in self.names() if (info := self.inspect(name, strict=False)) is not None]

    def image_info(self, image):
        result = self.w.run(['docker', 'image', 'inspect', image], timeout=30)
        if result['code']:
            if 'no such' in result['output'].lower():
                return None
            raise ValueError(result['output'])
        return json.loads(result['output'])[0]

    def image_archive(self, image_id):
        return self.w.root.parent / 'docker-images' / (hashlib.sha256(image_id.encode()).hexdigest() + '.tar')

    def save_image(self, image_id):
        destination = self.image_archive(image_id)
        if destination.exists():
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.image-', dir=destination.parent)
        os.close(fd)
        try:
            checked(self.w, ['docker', 'image', 'save', '--output', temporary, image_id], 600)
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def build_image(self, name, config):
        context = self.folder(name) / 'context'
        dockerfile = context / safe_path(config['dockerfile'])
        if not dockerfile.is_file() or not inside(dockerfile, context):
            raise ValueError('Dockerfile fehlt im hochgeladenen Build-Kontext.')
        command = ['docker', 'build', '--tag', config['image'], '--label', OWNER + '=' + name,
                   '--file', str(dockerfile)]
        for key, value in config['build_args'].items():
            command += ['--build-arg', key + '=' + value]
        if config['target']:
            command += ['--target', config['target']]
        output = checked(self.w, [*command, str(context)], 600)
        image = self.image_info(config['image'])
        self.save_image(image['Id'])
        self.w.write(self.folder(name) / '.studio-build.json', json.dumps({'image_id': image['Id']}))
        return output

    def ensure_image(self, name, config, pinned=None):
        if pinned:
            image = self.image_info(pinned['image_id'])
            if image is None:
                archive = self.image_archive(pinned['image_id'])
                if archive.exists():
                    checked(self.w, ['docker', 'image', 'load', '--input', str(archive)], 600)
                elif pinned.get('pull_ref'):
                    checked(self.w, ['docker', 'pull', pinned['pull_ref']], 600)
                else:
                    raise ValueError('Gesichertes lokales Image fehlt; Image bauen oder wiederherstellen.')
                image = self.image_info(pinned['image_id'])
                if image is None:
                    raise ValueError('Gesichertes Image ist auf diesem Zielsystem nicht verfügbar; Architektur prüfen.')
            return image
        image = self.image_info(config['image'])
        if config['build']:
            if image is None:
                previous = self.folder(name) / '.studio-build.json'
                if previous.exists():
                    ident = json.loads(previous.read_text())['image_id']
                    archive = self.image_archive(ident)
                    if self.image_info(ident) is None and archive.exists():
                        checked(self.w, ['docker', 'image', 'load', '--input', str(archive)], 600)
                    if self.image_info(ident):
                        checked(self.w, ['docker', 'tag', ident, config['image']], 30)
                if self.image_info(config['image']) is None:
                    self.build_image(name, config)
            return self.image_info(config['image'])
        if config['pull_policy'] == 'always' or (image is None and config['pull_policy'] != 'never'):
            checked(self.w, ['docker', 'pull', config['image']], 600)
            image = self.image_info(config['image'])
        if image is None:
            raise ValueError('Image ist lokal nicht vorhanden und automatisches Laden ist abgeschaltet.')
        return image

    def compile(self, name, config, image):
        config = copy.deepcopy(config)
        targets = {mount_parts(v, name)[1] for v in config['mounts']}
        for target in (image.get('Config', {}).get('Volumes') or {}):
            if target not in targets:
                config['mounts'].append(target)  # Persist implicit image volumes too.
        runtime = {'version': 1, 'config': config, 'image_id': image['Id'],
                   'pull_ref': (image.get('RepoDigests') or [''])[0],
                   'archive_image': config['build'] or not image.get('RepoDigests'),
                   'data_root': str(self.w.root.parent), 'volumes': []}
        command = ['docker', 'container', 'create', '--name', 'hd_' + name,
                   '--restart', config['restart'], '--network', config['network']]
        for option, key in (('--entrypoint', 'entrypoint'), ('--user', 'user'), ('--workdir', 'workdir'),
                            ('--hostname', 'hostname'), ('--memory', 'memory'), ('--cpus', 'cpus')):
            if config[key]:
                command += [option, config[key]]
        for key, value in config['env'].items():
            command += ['--env', key + '=' + value]
        for key, value in config['labels'].items():
            command += ['--label', key + '=' + value]
        for option, key in (('--publish', 'ports'), ('--cap-add', 'cap_add'), ('--cap-drop', 'cap_drop'),
                            ('--device', 'devices'), ('--add-host', 'add_hosts'), ('--dns', 'dns'), ('--tmpfs', 'tmpfs')):
            for value in config[key]:
                command += [option, value]
        if config['read_only']:
            command.append('--read-only')
        if config['privileged']:
            command.append('--privileged')
        if config['init']:
            command.append('--init')
        for value in config['mounts']:
            source, target, mode = mount_parts(value, name)
            if source in SOCKETS:
                command += ['--mount', f'type=bind,src={source},dst={target}' + (',readonly' if mode == 'ro' else '')]
            elif source.startswith('.'):
                directory = self.folder(name) / 'context' / safe_path(source)
                if not inside(directory, self.w.root.parent):
                    raise ValueError('Bind-Pfad liegt außerhalb der App-Daten.')
                if not directory.exists():
                    directory.mkdir(parents=True)
                command += ['--mount', f'type=bind,src={directory},dst={target}' + (',readonly' if mode == 'ro' else '')]
            else:
                directory = self.w.root.parent / 'storage' / 'docker-volumes' / hashlib.sha256(source.encode()).hexdigest()[:24]
                directory.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256(str(directory).encode()).hexdigest()[:24]
                volume = 'hdv_' + digest
                result = self.w.run(['docker', 'volume', 'inspect', volume], timeout=30)
                if result['code']:
                    if 'no such' not in result['output'].lower():
                        raise ValueError(result['output'])
                    checked(self.w, ['docker', 'volume', 'create', '--label', MANAGED + '=true',
                        '--driver', 'local', '--opt', 'type=none', '--opt', 'o=bind', '--opt', 'device=' + str(directory), volume], 30)
                else:
                    existing = json.loads(result['output'])[0]
                    if existing.get('Driver') != 'local' or existing.get('Options') != {'type': 'none', 'o': 'bind', 'device': str(directory)} or (existing.get('Labels') or {}).get(MANAGED) != 'true':
                        raise ValueError('Volume-Namenskonflikt; bestehendes Volume wird nicht verändert.')
                runtime['volumes'].append(volume)
                command += ['--mount', f'type=volume,src={volume},dst={target}' + (',readonly' if mode == 'ro' else '')]
        fingerprint = hashlib.sha256(json.dumps(runtime, sort_keys=True).encode()).hexdigest()
        command += ['--label', MANAGED + '=true', '--label', OWNER + '=' + name,
                    '--label', FINGERPRINT + '=' + fingerprint, image['Id'], *config['command']]
        runtime['fingerprint'] = fingerprint
        return runtime, command

    def apply(self, name, pinned=None):
        config = normalize(name, pinned['config'] if pinned else self.read(name)['config'])
        image = self.ensure_image(name, config, pinned)
        runtime, command = self.compile(name, config, image)
        existing = self.inspect(name)
        if existing and existing['labels'].get(FINGERPRINT) != runtime['fingerprint']:
            if existing['running']:
                checked(self.w, ['docker', 'stop', '--time', '30', 'hd_' + name], 120)
            checked(self.w, ['docker', 'container', 'rm', 'hd_' + name], 30)
            existing = None
        if runtime['archive_image']:
            self.save_image(image['Id'])
        if existing is None:
            checked(self.w, command, 60)
        self.w.write(self.folder(name) / '.studio-native-runtime.json', json.dumps(runtime))
        output = checked(self.w, ['docker', 'container', 'start', 'hd_' + name], 60)
        self.audit(name)
        return {'code': 0, 'output': 'Container gestartet: ' + output}

    def runtime(self, name):
        path = self.folder(name) / '.studio-native-runtime.json'
        if not path.exists():
            raise ValueError('Container besitzt noch keine angewendete Konfiguration.')
        return json.loads(path.read_text())

    def audit(self, name):
        info = self.inspect(name)
        if not info:
            return
        if not (self.folder(name) / '.studio-native-runtime.json').exists() and not info['running']:
            return  # Interrupted create: stopped container, no unrecorded writes.
        runtime = self.runtime(name)
        for mount in info['mounts']:
            if mount['Type'] == 'volume' and mount['Name'] not in runtime['volumes']:
                raise ValueError('Container verwendet ein nicht zugeordnetes Volume.')
            if mount['Type'] == 'bind' and mount['Source'] not in SOCKETS and not inside(mount['Source'], self.w.root.parent):
                raise ValueError('Container verwendet Daten außerhalb des App-Verzeichnisses.')

    def backup_images(self):
        for name in self.names():
            path = self.folder(name) / '.studio-native-runtime.json'
            if path.exists():
                runtime = json.loads(path.read_text())
                if runtime['archive_image']:
                    self.save_image(runtime['image_id'])
            build = self.folder(name) / '.studio-build.json'
            if build.exists():
                self.save_image(json.loads(build.read_text())['image_id'])

    def resume(self, name):
        return self.apply(name, pinned=self.runtime(name))

    def action(self, name, action, command=''):
        self.folder(name)
        allowed = {'up', 'stop', 'restart', 'remove', 'logs', 'status', 'pull', 'build', 'exec'}
        if action not in allowed:
            raise ValueError('Unbekannte Docker-Aktion.')
        exec_args = words(command) if action == 'exec' else []
        if action == 'exec' and not exec_args:
            raise ValueError('Befehl für docker exec fehlt.')
        def operation():
            config = self.read(name)['config']
            if action == 'up':
                return self.apply(name)
            if action == 'pull':
                if config['build']:
                    raise ValueError('Für ein Dockerfile-Projekt „Image bauen“ verwenden.')
                return self.w.run(['docker', 'pull', config['image']], timeout=600)
            if action == 'build':
                if not config['build']:
                    raise ValueError('Zuerst Dockerfile-Projekt aktivieren.')
                return {'code': 0, 'output': self.build_image(name, config) + '\nImage für das HA-Backup gespeichert. Zum Anwenden Container starten.'}
            info = self.inspect(name)
            if action == 'status':
                return {'code': 0, 'output': json.dumps(info or {'status': 'Noch kein Container angelegt.'}, indent=2, ensure_ascii=False)}
            if info is None:
                raise ValueError('Container ist noch nicht angelegt oder wurde entfernt.')
            commands = {'stop': ['container', 'stop', '--time', '30', 'hd_' + name],
                'restart': ['container', 'restart', '--time', '30', 'hd_' + name],
                'logs': ['container', 'logs', '--tail', '200', 'hd_' + name],
                'exec': ['container', 'exec', 'hd_' + name, *exec_args]}
            if action == 'remove':
                if info['running']:
                    checked(self.w, ['docker', 'container', 'stop', '--time', '30', 'hd_' + name], 120)
                return self.w.run(['docker', 'container', 'rm', 'hd_' + name], timeout=60)
            return self.w.run(['docker', *commands[action]], timeout=600)
        return self.w.launch('docker/' + name, action, operation)
