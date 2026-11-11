"""Supervisor hooks: stop data writers, save restart intent, resume after backup."""
import json
import sys
from pathlib import Path
from storage import audit, checked, containers, inside, legacy_volumes, prepare, rebase
from native import Native


class Backup:
    def __init__(self, workspace):
        self.workspace = workspace
        self.state = workspace.root.parent / '.studio-backup-state.json'
        self.native = Native(workspace)

    def pre(self, reason='backup'):
        w = self.workspace
        if not w.lock.acquire(blocking=False):
            raise BlockingIOError('Compose-Vorgang läuft. Backup anschließend erneut starten.')
        try:
            if self.state.exists():
                raise ValueError('Vorheriger Stopp/Backup muss zuerst fortgesetzt werden.')
            found = containers(w)
            running = [c for c in found if c['running']]
            docker_found = self.native.containers()
            docker_running = [c for c in docker_found if c['running']]
            projects = sorted({c['labels']['com.docker.compose.project'][3:] for c in running})
            state = {'version': 1, 'reason': reason, 'projects': projects,
                     'containers': [c['id'] for c in running + docker_running], 'ready': False,
                     'docker': [c['name'] for c in docker_running],
                     'by_project': {name: [c['id'] for c in running if c['labels']['com.docker.compose.project'] == 'cs_' + name] for name in projects}}
            w.write(self.state, json.dumps(state))
            try:
                if state['containers']:
                    checked(w, ['docker', 'stop', '--time', '30', *state['containers']], 120)
                for name in w.list_projects():
                    existing = [c for c in found if c['labels']['com.docker.compose.project'] == 'cs_' + name]
                    if (w.project(name) / '.studio-runtime.json').exists():
                        rebase(w, name)
                    elif existing or legacy_volumes(w, name):
                        prepare(w, name)
                    audit(w, name)
                # Refuse incomplete snapshots from legacy unsupported host mounts.
                for container in found:
                    for mount in container['mounts']:
                        if mount['Type'] == 'bind' and not inside(mount['Source'], w.root.parent):
                            raise ValueError('Ein bestehender Container nutzt Daten außerhalb des App-Datenordners.')
                for container in docker_found:
                    self.native.audit(container['name'])
                self.native.backup_images()
                state['ready'] = True
                w.write(self.state, json.dumps(state))
            except Exception:
                self.resume(state)
                self.state.unlink(missing_ok=True)
                raise
        finally:
            w.lock.release()

    def post(self):
        w = self.workspace
        if not w.lock.acquire(blocking=False):
            raise BlockingIOError('Compose-Vorgang läuft.')
        try:
            if not self.state.exists():
                return
            state = json.loads(self.state.read_text())
            self.resume(state)
            self.state.unlink()
        finally:
            w.lock.release()

    def resume(self, state):
        w = self.workspace
        for name in state['projects']:
            if (w.project(name) / '.studio-runtime.json').exists():
                rebase(w, name)
                checked(w, w.command(name, 'up', '-d', '--no-build'), 600)
            else:
                ids = state.get('by_project', {}).get(name, [])
                if ids:
                    checked(w, ['docker', 'start', *ids], 120)
        for name in state.get('docker', []):
            self.native.resume(name)


def main():
    from server import Workspace, discover_data_source, mirror_data_source
    workspace = Workspace(mirror_data_source(discover_data_source()))
    backup = Backup(workspace)
    if sys.argv[1:] == ['pre']:
        backup.pre()
    elif sys.argv[1:] == ['post']:
        backup.post()
    else:
        raise ValueError('Aufruf: backups.py pre|post')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
