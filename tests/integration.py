"""Real Docker integration; run from repository root after building :dev.

Only loopback is published. Mimics HA ingress at 172.30.32.2, including its URL
prefix. Set KEEP_TEST_APP=1 to retain the test deployment for browser checks;
run again without it to clean up after checks (resources have fixed test names).
"""
import http.client
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT.parent / 'integration-data'
APP_NAME = 'compose-studio-integration-app'
PROXY_NAME = 'compose-studio-integration-proxy'
NETWORK = 'compose-studio-integration-net'
PROJECT = 'integration-probe'
PREFIX = '/api/hassio_ingress/integration-token/'
BASE = 'http://127.0.0.1:18099' + PREFIX


def docker(*args, check=True):
    return subprocess.run(['docker', *args], text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, check=check).stdout.strip()


def cleanup():
    # Each resource name/label belongs exclusively to this test.
    ids = docker('ps', '-aq', '--filter', 'label=com.docker.compose.project=cs_' + PROJECT).split()
    if ids:
        docker('rm', '-f', *ids, check=False)
    docker('rm', '-f', PROXY_NAME, APP_NAME, check=False)
    docker('network', 'rm', 'cs_' + PROJECT + '_default', check=False)
    volumes = docker('volume', 'ls', '-q', '--filter', 'label=com.docker.compose.project=cs_' + PROJECT).split()
    if volumes:
        docker('volume', 'rm', *volumes, check=False)
    docker('volume', 'rm', 'cs_' + PROJECT + '_kept', check=False)
    docker('network', 'rm', NETWORK, check=False)


PROXY = '''
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
class Proxy(BaseHTTPRequestHandler):
    def forward(self):
        prefix = '/api/hassio_ingress/integration-token'
        if not self.path.startswith(prefix + '/'):
            self.send_error(404); return
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        headers = dict(self.headers)
        headers['X-Ingress-Path'] = prefix
        conn = http.client.HTTPConnection('compose-studio-integration-app', 8099, timeout=30)
        try:
            conn.request(self.command, self.path[len(prefix):], body, headers)
            response = conn.getresponse()
            result = response.read()
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in ('connection', 'transfer-encoding', 'server', 'date'):
                    self.send_header(key, value)
            self.end_headers(); self.wfile.write(result)
        except OSError:
            self.send_error(503)
        finally:
            conn.close()
    do_GET = forward
    do_POST = forward
ThreadingHTTPServer(('0.0.0.0', 8099), Proxy).serve_forever()
'''
token = ''


def run_app(data):
    trust = []
    certificate = os.environ.get('CODEX_PROXY_CERT')
    if certificate:
        trust = ['--mount', f'type=bind,src={certificate},dst=/run/cloud-ca.pem,readonly',
                 '-e', 'SSL_CERT_FILE=/run/cloud-ca.pem']
    docker('run', '-d', '--name', APP_NAME, '--network', NETWORK, '--ip', '172.30.32.3',
           '--mount', 'type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock,readonly',
           '--mount', f'type=bind,src={data},dst=/data', *trust, 'compose-studio:dev')


def request(path='', body=None, authenticated=True):
    headers = {'X-Compose-Token': token} if authenticated else {}
    if body is not None:
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(BASE + path, headers=headers,
                                 data=None if body is None else json.dumps(body).encode())
    with urllib.request.urlopen(req, timeout=10) as response:
        content = response.read()
        return json.loads(content) if response.headers.get_content_type() == 'application/json' else content.decode()


def action(name):
    result = request('api/projects/' + PROJECT + '/actions', {'action': name})
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        job = request('api/jobs/' + result['id'])
        if job['state'] != 'running':
            assert job['code'] == 0, job
            print('PASS', name, flush=True)
            return job['output']
        time.sleep(0.2)
    raise AssertionError('Vorgang nicht rechtzeitig abgeschlossen')


def main():
    global token
    cleanup()
    DATA.mkdir(parents=True, exist_ok=True)
    try:
        docker('pull', 'busybox:1.37.0')
        docker('network', 'create', '--subnet', '172.30.32.0/24', NETWORK)
        run_app(DATA)
        docker('run', '-d', '--name', PROXY_NAME, '--network', NETWORK, '--ip', '172.30.32.2',
               '-p', '127.0.0.1:18099:8099', 'python:3.13-alpine3.22', 'python3', '-u', '-c', PROXY)
        for attempt in range(40):
            try:
                html = request(authenticated=False)
                break
            except (OSError, urllib.error.URLError):
                time.sleep(0.25)
        else:
            raise AssertionError(docker('logs', APP_NAME))
        token = re.search(r'name="compose-token" content="([^"]+)"', html)[1]
        assert request('api/projects')['compose_version'].lstrip('v').startswith('2.')
        denied = docker('exec', APP_NAME, 'python3', '-c',
                        'import http.client;c=http.client.HTTPConnection("127.0.0.1",8099);'
                        'c.request("GET","/");print(c.getresponse().status)')
        assert denied == '403', denied
        print('PASS ingress prefix, Compose V2, direct access denied', flush=True)
        config = {'services': {'writer': {
            'image': 'busybox:1.37.0',
            'environment': {'NOTE': '${NOTE}'},
            'command': ['sh', '-c', 'printf "%s" "$$NOTE" > /result/probe.txt; echo durable > /kept/marker; echo compose-log-ok; sleep 300'],
            'volumes': ['./files:/result', 'kept:/kept'],
        }}, 'volumes': {'kept': {}}}
        saved = request('api/projects/' + PROJECT, {'compose': json.dumps(config), 'env': 'NOTE=compose-ok\n'})
        assert saved['host_path'] == str(DATA / 'stacks' / PROJECT)
        action('validate')
        action('up')
        # Read through the app: a rootless daemon may map container-owned files
        # to UIDs the outer test user cannot read directly.
        assert docker('exec', APP_NAME, 'cat', '/data/stacks/' + PROJECT + '/files/probe.txt') == 'compose-ok'
        mounts = json.loads(docker('inspect', 'cs_' + PROJECT + '-writer-1', '--format', '{{json .Mounts}}'))
        assert next(m['Source'] for m in mounts if m['Destination'] == '/result') == str(DATA / 'stacks' / PROJECT / 'files')
        print('PASS actual relative host bind mount and .env interpolation', flush=True)
        assert 'writer' in action('ps')
        assert 'compose-log-ok' in action('logs')
        action('stop')
        action('restart')
        # Mimic Supervisor's hot backup ordering, including the durable restart marker.
        docker('exec', APP_NAME, 'python3', '/app/backups.py', 'pre')
        assert docker('inspect', 'cs_' + PROJECT + '-writer-1', '--format', '{{.State.Running}}') == 'false'
        try:
            request('api/projects/' + PROJECT, {'compose': json.dumps(config), 'env': 'NOTE=changed'})
            raise AssertionError('Writes must be blocked during a backup')
        except urllib.error.HTTPError as error:
            assert error.code == 409
        backup_file = ROOT.parent / 'integration-ha-backup.tar.gz'
        with backup_file.open('wb') as stream:
            subprocess.run(['docker', 'exec', APP_NAME, 'tar', '-czpf', '-', '-C', '/data', '.'], stdout=stream, check=True)
        docker('exec', APP_NAME, 'python3', '/app/backups.py', 'post')
        assert docker('exec', 'cs_' + PROJECT + '-writer-1', 'cat', '/kept/marker') == 'durable'
        print('PASS backup hooks stop writers, block edits, and resume projects', flush=True)
        docker('exec', 'cs_' + PROJECT + '-writer-1', 'sh', '-c', 'echo later > /kept/marker')
        runtime = json.loads(docker('exec', APP_NAME, 'cat', '/data/stacks/' + PROJECT + '/.studio-runtime.json'))
        managed_volume = runtime['volumes']['kept']['name']
        device = json.loads(docker('volume', 'inspect', managed_volume))[0]['Options']['device']
        assert device.startswith(str(DATA / 'storage'))
        action('down')
        assert docker('volume', 'inspect', managed_volume, '--format', '{{.Name}}')
        print('PASS named volume retained after down', flush=True)
        # Restore the app backup onto a different host data path; old Docker
        # volumes deliberately remain, so a stale path/name cannot pass this test.
        docker('stop', '--time', '60', APP_NAME)
        docker('rm', APP_NAME)
        restored_data = ROOT.parent / 'integration-restored'
        restored_data.mkdir(exist_ok=True)
        docker('run', '--rm', '--network', 'none',
              '--mount', f'type=bind,src={restored_data},dst=/restore',
              '--entrypoint', 'python3', 'python:3.13-alpine3.22', '-c',
              'from pathlib import Path; import shutil; '
              '[(p.unlink() if p.is_symlink() or p.is_file() else shutil.rmtree(p)) for p in Path("/restore").iterdir()]')
        with backup_file.open('rb') as stream:
            subprocess.run(['docker', 'run', '--rm', '-i', '--network', 'none',
                '--mount', f'type=bind,src={restored_data},dst=/restore',
                '--entrypoint', 'tar', 'python:3.13-alpine3.22', '-xzpf', '-', '-C', '/restore'], stdin=stream, check=True)
        run_app(restored_data)
        for attempt in range(40):
            try:
                html = request(authenticated=False)
                token = re.search(r'name="compose-token" content="([^"]+)"', html)[1]
                assert request('api/projects/' + PROJECT)['env'] == 'NOTE=compose-ok\n'
                break
            except (OSError, urllib.error.URLError):
                time.sleep(0.25)
        else:
            raise AssertionError('Persistence check failed')
        restored_runtime = json.loads(docker('exec', APP_NAME, 'cat', '/data/stacks/' + PROJECT + '/.studio-runtime.json'))
        assert restored_runtime['volumes']['kept']['name'] != managed_volume
        assert docker('exec', 'cs_' + PROJECT + '-writer-1', 'cat', '/kept/marker') == 'durable'
        restored_mounts = json.loads(docker('inspect', 'cs_' + PROJECT + '-writer-1', '--format', '{{json .Mounts}}'))
        assert next(m['Source'] for m in restored_mounts if m['Destination'] == '/result').startswith(str(restored_data))
        print('PASS restore to a different data path: volume contents, bind files, .env, auto-resume', flush=True)
        if os.environ.get('KEEP_TEST_APP') == '1':
            print('Test app retained at ' + BASE, flush=True)
    finally:
        if os.environ.get('KEEP_TEST_APP') != '1':
            cleanup()


if __name__ == '__main__':
    main()
