"""Check HA's /run socket mount, legacy fallback, and missing-mount diagnostics."""
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT.parent / 'socket-probe-data'
NAME = 'docker-studio-socket-probe'
SOCKET = next(p for p in (Path('/run/docker.sock'), Path('/var/run/docker.sock')) if p.is_socket())
ENV = {k: v for k, v in os.environ.items() if k not in
       {'DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'}}


def docker(*args, check=True):
    return subprocess.run(['docker', '--host', 'unix://' + str(SOCKET), *args], env=ENV,
                          capture_output=True, text=True, check=check)


def main():
    missing = docker('run', '--rm', '--network', 'none', 'compose-studio:dev', check=False)
    assert missing.returncode == 1
    assert 'kein Docker-Socket' in missing.stderr and 'Schutzmodus' in missing.stderr
    assert 'Traceback' not in missing.stderr
    print('PASS missing socket: clear protection-mode instructions without traceback', flush=True)
    DATA.mkdir(exist_ok=True)
    docker('rm', '-f', NAME, check=False)
    try:
        # Deliberately break the Alpine /var/run -> /run alias. Only HA's real
        # mount at /run/docker.sock remains; a hardcoded /var/run endpoint fails.
        boot = "from pathlib import Path; p=Path('/var/run'); p.unlink(); p.mkdir(); from server import main; main()"
        docker('run', '-d', '--name', NAME, '--network', 'none',
               '--mount', f'type=bind,src={SOCKET},dst=/run/docker.sock,readonly',
               '--mount', f'type=bind,src={DATA},dst=/data',
               '--entrypoint', 'python3', 'compose-studio:dev', '-c', boot)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            probe = docker('exec', NAME, 'python3', '-c',
                "import http.client;c=http.client.HTTPConnection('127.0.0.1',8099,timeout=2);c.request('GET','/');print(c.getresponse().status)", check=False)
            if probe.returncode == 0:
                assert probe.stdout.strip() == '403'  # Ingress IP guard still applies.
                break
            time.sleep(0.25)
        else:
            raise AssertionError(docker('logs', NAME).stdout)
        endpoint = docker('exec', NAME, 'python3', '-c',
            "from server import require_docker_socket,DOCKER_ENV;require_docker_socket();print(DOCKER_ENV['DOCKER_HOST'])")
        assert endpoint.stdout.strip() == 'unix:///run/docker.sock'
        print('PASS full app startup with HA /run socket and no /var/run alias; Ingress guard retained', flush=True)
    finally:
        docker('stop', '--time', '30', NAME, check=False)
        docker('rm', '-f', NAME, check=False)
    fallback = "from pathlib import Path;p=Path('/var/run');p.unlink();p.mkdir();(p/'docker.sock').symlink_to('/probe/docker.sock');from server import require_docker_socket,discover_data_source,DOCKER_ENV;require_docker_socket();assert DOCKER_ENV['DOCKER_HOST']=='unix:///var/run/docker.sock';assert discover_data_source();print('legacy-ok')"
    legacy = docker('run', '--rm', '--network', 'none',
        '--mount', f'type=bind,src={SOCKET},dst=/probe/docker.sock,readonly',
        '--mount', f'type=bind,src={DATA},dst=/data',
        '--entrypoint', 'python3', 'compose-studio:dev', '-c', fallback)
    assert legacy.stdout.strip() == 'legacy-ok'
    print('PASS legacy socket fallback with real Docker connection and self data-path discovery', flush=True)


if __name__ == '__main__':
    main()
