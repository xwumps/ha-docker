"""Home Assistant Ingress app for a private, scoped Compose V2 workspace."""
import hmac
import base64
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from storage import OperationLock, audit, checked, containers, legacy_volumes, prepare, rebase

DATA = Path('/data')
APP = Path(__file__).parent
NAME = re.compile(r'[a-z][a-z0-9_-]{0,39}\Z')
TOKEN = secrets.token_urlsafe(32)
INGRESS_IP = '172.30.32.2'
MAX_BODY = 18 * 1024 * 1024
MAX_OUTPUT = 128 * 1024
SHUTTING_DOWN = threading.Event()
PROCESSES = set()
PROCESSES_LOCK = threading.Lock()
# Do not expose the Supervisor token or inherited variables to Compose interpolation.
DOCKER_ENV = {
    'PATH': os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin'),
    'HOME': '/data', 'LANG': 'C.UTF-8', 'COMPOSE_ANSI': 'never',
    'DOCKER_HOST': 'unix:///var/run/docker.sock',
    'DOCKER_CONFIG': '/data/docker-config',
}


def run_command(args, cwd=None, timeout=600):
    """Bound memory usage, capture diagnostics, and terminate the process group."""
    with tempfile.TemporaryFile() as output:
        proc = subprocess.Popen(args, cwd=cwd, env=DOCKER_ENV, stdin=subprocess.DEVNULL,
                                stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        with PROCESSES_LOCK:
            PROCESSES.add(proc)
        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
        finally:
            with PROCESSES_LOCK:
                PROCESSES.discard(proc)
        size = output.tell()
        output.seek(max(0, size - MAX_OUTPUT))
        text = output.read().decode('utf-8', errors='replace')
        if size > MAX_OUTPUT:
            text = '[Ausgabe gekürzt; letzte 128 KiB]\n' + text
        if timed_out:
            text += '\nZeitlimit erreicht. Docker kann bereits gestartete Vorgänge weiter ausführen; Status prüfen.'
        return {'code': 124 if timed_out else proc.returncode, 'output': text}


def discover_data_source():
    """Find our /data bind by Config.Hostname, even with a custom HA hostname."""
    listing = run_command(['docker', 'ps', '-q'], timeout=20)
    if listing['code']:
        raise RuntimeError('Docker nicht erreichbar. Schutzmodus dieser App ausschalten.\n' + listing['output'])
    ids = listing['output'].split()
    if not ids:
        raise RuntimeError('Eigener App-Container wurde nicht gefunden.')
    inspect_format = '{"hostname":{{json .Config.Hostname}},"mounts":{{json .Mounts}}}'
    inspected = run_command(['docker', 'inspect', '--format', inspect_format, *ids], timeout=20)
    if inspected['code']:
        raise RuntimeError('Container-Metadaten konnten nicht gelesen werden: ' + inspected['output'])
    candidates = []
    for line in inspected['output'].splitlines():
        container = json.loads(line)
        if container['hostname'] == socket.gethostname():
            candidates.extend(m['Source'] for m in container['mounts']
                              if m.get('Destination') == '/data' and m.get('Type') == 'bind')
    if len(candidates) != 1:
        raise RuntimeError('Der /data-Host-Pfad ist nicht eindeutig. Start abgebrochen.')
    source = Path(candidates[0])
    if not source.is_absolute() or source == Path('/'):
        raise RuntimeError('Ungültiger Docker-Datenpfad.')
    return source


def mirror_data_source(source):
    """Expose /data at its Docker host path for relative bind mounts and builds."""
    if source != DATA:
        source.parent.mkdir(parents=True, exist_ok=True)
        if os.path.lexists(source):
            if not source.is_symlink() or source.resolve() != DATA.resolve():
                raise RuntimeError(f'Host-Pfad {source} ist in der App bereits belegt.')
        else:
            source.symlink_to(DATA, target_is_directory=True)
    return source


def atomic_write(path, text):
    fd, temporary = tempfile.mkstemp(prefix='.save-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Workspace:
    def __init__(self, root):
        # Do not resolve this path: Compose must see the Docker HOST path.
        self.root = root / 'stacks'
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = OperationLock(root / '.studio-operation.lock')
        self.jobs_lock = threading.Lock()
        self.jobs = {}
        self.active = None

    def run(self, *args, **kwargs):
        return run_command(*args, **kwargs)

    write = staticmethod(atomic_write)

    def check_available(self):
        if SHUTTING_DOWN.is_set() or (self.root.parent / '.studio-backup-state.json').exists():
            raise BlockingIOError('Backup oder App-Stopp läuft. Bitte warten.')

    def project(self, name, exists=True):
        if not isinstance(name, str) or not NAME.fullmatch(name):
            raise ValueError('Projektname: 1–40 Zeichen, mit a–z beginnen; danach a–z, 0–9, _ oder -.')
        path = self.root / name
        if path.is_symlink():
            raise ValueError('Symlinks als Projektverzeichnis sind nicht erlaubt.')
        if exists and not (path / 'compose.yaml').is_file():
            raise FileNotFoundError('Projekt nicht gefunden.')
        for filename in ('compose.yaml', '.env'):
            if (path / filename).is_symlink():
                raise ValueError('Symlinks als Konfigurationsdateien sind nicht erlaubt.')
        return path

    def list_projects(self):
        return sorted(p.name for p in self.root.iterdir()
                      if NAME.fullmatch(p.name) and not p.is_symlink() and (p / 'compose.yaml').is_file())

    def read(self, name):
        path = self.project(name)
        return {'name': name, 'compose': (path / 'compose.yaml').read_text(),
                'env': (path / '.env').read_text() if (path / '.env').exists() else '',
                'host_path': str(path), 'storage_path': str(self.root.parent / 'storage' / name),
                'project_name': 'cs_' + name}

    def save(self, name, compose, env):
        if not isinstance(compose, str) or not compose.strip() or not isinstance(env, str):
            raise ValueError('Compose-YAML darf nicht leer sein; .env muss Text sein.')
        if len(compose.encode()) + len(env.encode()) > 512 * 1024:
            raise ValueError('YAML und .env dürfen zusammen maximal 512 KiB groß sein.')
        self.check_available()
        if not self.lock.acquire(blocking=False):
            raise BlockingIOError('Ein Vorgang läuft. Bitte warten.')
        try:
            self.check_available()
            path = self.project(name, exists=False)
            path.mkdir(mode=0o700, exist_ok=True)
            atomic_write(path / '.env', env)
            atomic_write(path / 'compose.yaml', compose)
        finally:
            self.lock.release()
        return self.read(name)

    def command(self, name, *arguments, runtime=True):
        path = self.project(name)
        config = '.studio-runtime.json' if runtime and (path / '.studio-runtime.json').exists() else 'compose.yaml'
        return ['docker', 'compose', '--ansi', 'never', '--project-name', 'cs_' + name,
                '--project-directory', str(path), '--env-file', str(path / '.env'),
                '-f', str(path / config), *arguments]

    def files(self, name):
        project = self.project(name)
        found = []
        for directory, folders, files in os.walk(project, followlinks=False):
            folders[:] = [f for f in folders if not f.startswith('.studio') and not (Path(directory) / f).is_symlink()]
            for filename in files:
                path = Path(directory) / filename
                if not filename.startswith('.studio') and not path.is_symlink():
                    found.append(str(path.relative_to(project)))
                    if len(found) >= 300:
                        return sorted(found)
        return sorted(found)

    def save_file(self, name, filename, encoded):
        from importers import safe_path
        self.check_available()
        project = self.project(name)
        relative = safe_path(filename)
        if str(relative) in ('compose.yaml', '.env'):
            raise ValueError('Compose-YAML und .env bitte im Editor bearbeiten.')
        data = base64.b64decode(encoded, validate=True)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError('Zusatzdateien dürfen maximal 2 MiB groß sein.')
        if not self.lock.acquire(blocking=False):
            raise BlockingIOError('Ein Vorgang läuft.')
        try:
            self.check_available()
            path = project / relative
            for parent in (path, *path.parents):
                if parent == project:
                    break
                if parent.is_symlink():
                    raise ValueError('Symlinks dürfen nicht überschrieben werden.')
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix='.save-', dir=path.parent)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(data)
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return {'files': self.files(name)}
        finally:
            self.lock.release()

    def start(self, name, action):
        commands = {
            'validate': ['config', '--quiet'], 'up': ['up', '-d', '--no-build'],
            'stop': ['stop', '--timeout', '20'], 'down': ['down', '--timeout', '20'],
            'restart': ['restart', '--timeout', '20'], 'pull': ['pull'],
            'ps': ['ps', '--all'], 'logs': ['logs', '--no-color', '--tail', '200'],
        }
        if action not in commands:
            raise ValueError('Unbekannte Aktion.')
        self.project(name)
        self.check_available()
        if not self.lock.acquire(blocking=False):
            raise BlockingIOError('Ein Vorgang läuft. Bitte warten.')
        job_id = secrets.token_hex(12)
        with self.jobs_lock:
            if len(self.jobs) >= 25:
                self.jobs.pop(next(iter(self.jobs)))
            self.jobs[job_id] = {'id': job_id, 'name': name, 'action': action, 'state': 'running'}
            self.active = job_id
        def worker():
            try:
                self.check_available()
                if action == 'up':
                    result = run_command(self.command(name, 'config', '--quiet', runtime=False), timeout=30)
                    if result['code']:
                        with self.jobs_lock:
                            self.jobs[job_id].update(result, state='failed')
                        return
                    running = [c['id'] for c in containers(self, name) if c['running']]
                    if running:
                        checked(self, ['docker', 'stop', '--time', '30', *running], 120)
                    try:
                        prepare(self, name)
                    except Exception:
                        if running:
                            checked(self, ['docker', 'start', *running], 120)
                        raise
                result = run_command(self.command(name, *commands[action], runtime=action != 'validate'), timeout=600)
                if action == 'up' and not result['code']:
                    try:
                        audit(self, name)
                    except Exception:
                        ids = [c['id'] for c in containers(self, name) if c['running']]
                        if ids:
                            checked(self, ['docker', 'stop', '--time', '30', *ids], 120)
                        raise
                with self.jobs_lock:
                    self.jobs[job_id].update(result, state='done' if result['code'] == 0 else 'failed')
            except Exception as error:
                with self.jobs_lock:
                    self.jobs[job_id].update(code=1, output=str(error), state='failed')
            finally:
                with self.jobs_lock:
                    self.active = None
                self.lock.release()
        threading.Thread(target=worker, daemon=True).start()
        return {'id': job_id}

    def job(self, job_id):
        with self.jobs_lock:
            if job_id not in self.jobs:
                raise FileNotFoundError('Vorgang nicht gefunden (App eventuell neu gestartet).')
            return dict(self.jobs[job_id])


class Handler(BaseHTTPRequestHandler):
    server_version = 'ComposeStudio'

    def log_message(self, fmt, *args):
        # Avoid logging credentials, Compose contents, or ingress headers.
        print('%s %s' % (self.command, self.path.split('?')[0]), flush=True)

    def reply(self, status, value, content_type='application/json; charset=utf-8'):
        body = json.dumps(value, ensure_ascii=False).encode() if 'json' in content_type else value
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy',
                         "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'self'")
        self.end_headers()
        self.wfile.write(body)

    def dispatch(self):
        if self.client_address[0] != INGRESS_IP:
            self.reply(403, {'error': 'Nur über Home Assistant Ingress zugänglich.'})
            return
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            self.reply(403, {'error': 'Fremder Ursprung abgewiesen.'})
            return
        path = urlsplit(self.path).path
        static = {'/': ('index.html', 'text/html; charset=utf-8'),
                  '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                  '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if self.command == 'GET' and path in static:
            filename, mime = static[path]
            body = (APP / filename).read_bytes()
            if filename == 'index.html':
                body = body.replace(b'__CS_TOKEN__', TOKEN.encode())
            self.reply(200, body, mime)
            return
        if not hmac.compare_digest(self.headers.get('X-Compose-Token', ''), TOKEN):
            self.reply(403, {'error': 'Sitzung abgelaufen. Oberfläche neu laden.'})
            return
        workspace = self.server.workspace
        parts = path.strip('/').split('/')
        if self.command == 'GET' and path == '/api/projects':
            with workspace.jobs_lock:
                active = workspace.active
            self.reply(200, {'projects': workspace.list_projects(), 'active_job': active,
                             'host_root': str(workspace.root), 'compose_version': self.server.compose_version,
                             'backup_paused': (workspace.root.parent / '.studio-backup-state.json').exists()})
        elif self.command == 'POST' and path == '/api/import':
            from importers import install_archive, install_jotion
            data = self.body()
            if data.get('kind') == 'jotion':
                result = install_jotion(workspace, data.get('name'), data.get('version', ''),
                                        data.get('public_url', ''), data.get('port'))
            elif data.get('kind') == 'archive':
                result = install_archive(workspace, data.get('name'), base64.b64decode(data.get('archive', ''), validate=True))
            else:
                raise ValueError('Unbekannter Importtyp.')
            self.reply(201, result)
        elif len(parts) == 4 and parts[:2] == ['api', 'projects'] and parts[3] == 'files':
            if self.command == 'GET':
                self.reply(200, {'files': workspace.files(parts[2])})
            elif self.command == 'POST':
                data = self.body()
                self.reply(200, workspace.save_file(parts[2], data.get('path'), data.get('content')))
            else:
                self.reply(405, {'error': 'Methode nicht erlaubt.'})
        elif self.command == 'GET' and len(parts) == 3 and parts[:2] == ['api', 'jobs']:
            self.reply(200, workspace.job(parts[2]))
        elif len(parts) == 3 and parts[:2] == ['api', 'projects']:
            if self.command == 'GET':
                self.reply(200, workspace.read(parts[2]))
            elif self.command == 'POST':
                data = self.body()
                self.reply(200, workspace.save(parts[2], data.get('compose'), data.get('env', '')))
            else:
                self.reply(405, {'error': 'Methode nicht erlaubt.'})
        elif self.command == 'POST' and len(parts) == 4 and parts[:2] == ['api', 'projects'] and parts[3] == 'actions':
            self.reply(202, workspace.start(parts[2], self.body().get('action')))
        else:
            self.reply(404, {'error': 'Nicht gefunden.'})

    def body(self):
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            raise ValueError('JSON wird erwartet.')
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 < length <= MAX_BODY:
            raise ValueError('Anfrage leer oder größer als 18 MiB.')
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict):
            raise ValueError('JSON-Objekt wird erwartet.')
        return data

    def handle_request(self):
        self.connection.settimeout(30)
        try:
            self.dispatch()
        except BlockingIOError as error:
            self.reply(409, {'error': str(error)})
        except FileNotFoundError as error:
            self.reply(404, {'error': str(error)})
        except (ValueError, TypeError) as error:
            self.reply(400, {'error': str(error)})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except Exception as error:
            print(f'Anfragefehler: {type(error).__name__}: {error}', flush=True)
            self.reply(500, {'error': 'Interner Fehler. App-Protokoll prüfen.'})

    do_GET = handle_request
    do_POST = handle_request


def main():
    os.umask(0o077)
    version = run_command(['docker', 'compose', 'version', '--short'], timeout=20)
    if version['code'] or not version['output'].strip().lstrip('v').startswith('2.'):
        raise RuntimeError('Docker Compose V2 wird benötigt: ' + version['output'])
    root = mirror_data_source(discover_data_source())
    workspace = Workspace(root)
    from backups import Backup
    backup = Backup(workspace)
    backup.post()  # Resume after a stopped app or a restored Home Assistant backup.
    legacy = [name for name in workspace.list_projects()
              if not (workspace.project(name) / '.studio-runtime.json').exists()
              and (containers(workspace, name) or legacy_volumes(workspace, name))]
    if legacy:
        print('Bestehende Projekte werden in den gesicherten App-Speicher übernommen …', flush=True)
        backup.pre(reason='upgrade')
        backup.post()
    def shutdown(signum, frame):
        SHUTTING_DOWN.set()
        with PROCESSES_LOCK:
            pending = list(PROCESSES)
        for proc in pending:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        if not workspace.lock.acquire(timeout=35):
            raise RuntimeError('Laufender Vorgang konnte für den App-Stopp nicht beendet werden.')
        workspace.lock.release()
        if not backup.state.exists():
            backup.pre(reason='shutdown')
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    server = ThreadingHTTPServer(('0.0.0.0', 8099), Handler)
    server.workspace = workspace
    server.compose_version = version['output'].strip()
    print(f'Compose Studio: Compose {server.compose_version}; Projekte: {server.workspace.root}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
