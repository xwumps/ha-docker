'use strict';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="compose-token"]').content;
const example = 'services:\n  web:\n    image: nginx:1.28-alpine\n    restart: unless-stopped\n    ports:\n      - "${WEB_PORT:-8090}:80"\n    mem_limit: 128m\n    cpus: 0.5\n';
const fields = ['name', 'compose', 'env'];
let selected = null, dirty = false, busy = false, saved = false;
function message(text, error = false) { $('message').textContent = text; $('message').className = error ? 'error' : ''; }
function renderControls() {
  document.querySelectorAll('button').forEach(button => {
    button.disabled = busy || (!!button.dataset.action && (!saved || dirty));
  });
  fields.forEach(id => { $(id).disabled = busy || (id === 'name' && saved); });
  $('dirty').textContent = dirty ? 'Ungespeichert' : saved ? 'Gespeichert' : 'Entwurf';
}
async function api(path, body) {
  const response = await fetch('api/' + path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: {'X-Compose-Token': token, ...(body === undefined ? {} : {'Content-Type': 'application/json'})},
    ...(body === undefined ? {} : {body: JSON.stringify(body)}),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Anfrage fehlgeschlagen.');
  return data;
}
function canLeave() { return !dirty || confirm('Ungespeicherte Änderungen verwerfen?'); }
function markDirty() { dirty = true; renderControls(); }
fields.forEach(id => $(id).addEventListener('input', markDirty));
window.addEventListener('beforeunload', event => { if (dirty || busy) { event.preventDefault(); event.returnValue = ''; } });
for (const id of ['compose', 'env']) $(id).addEventListener('keydown', event => {
  if (event.key === 'Tab') {
    event.preventDefault(); const field = event.target, start = field.selectionStart, end = field.selectionEnd;
    field.setRangeText('  ', start, end, 'end'); markDirty();
  }
});
async function refreshList() {
  const data = await api('projects');
  $('root').textContent = data.host_root;
  $('version').textContent = 'Compose ' + data.compose_version;
  $('projects').replaceChildren();
  data.projects.forEach(name => {
    const button = document.createElement('button'); button.textContent = name;
    if (name === selected) button.className = 'selected';
    button.addEventListener('click', () => { if (canLeave()) load(name); });
    $('projects').append(button);
  });
  if (!data.projects.length) $('projects').textContent = 'Noch keine Projekte.';
  renderControls(); return data;
}
function fill(data) {
  selected = data.name; saved = true; dirty = false;
  $('name').value = data.name; $('compose').value = data.compose; $('env').value = data.env;
  $('title').textContent = data.name;
  $('location').textContent = 'Host: ' + data.host_path + ' · Compose-Projekt: ' + data.project_name;
  renderControls();
}
async function load(name) {
  busy = true; renderControls(); message('');
  try { fill(await api('projects/' + encodeURIComponent(name))); await refreshList(); }
  catch (error) { message(error.message, true); }
  finally { busy = false; renderControls(); }
}
function newProject() {
  if (!canLeave()) return;
  selected = null; saved = false; dirty = false;
  $('name').value = ''; $('compose').value = example; $('env').value = 'WEB_PORT=8090\n';
  $('title').textContent = 'Neues Projekt'; $('location').textContent = 'Speichere zuerst dein Projekt.';
  message(''); renderControls(); $('name').focus();
  document.querySelectorAll('nav button').forEach(button => button.classList.remove('selected'));
}
$('new').addEventListener('click', newProject);
$('save').addEventListener('click', async () => {
  const name = $('name').value.trim();
  if (!/^[a-z][a-z0-9_-]{0,39}$/.test(name)) { message('Projektname: mit a–z beginnen, maximal 40 Zeichen aus a–z, 0–9, _ und -.', true); return; }
  busy = true; renderControls();
  try {
    // Never silently overwrite a different existing project from the New form.
    if (!saved && (await api('projects')).projects.includes(name)) throw new Error('Name bereits vorhanden. Projekt links öffnen.');
    fill(await api('projects/' + encodeURIComponent(name), {compose: $('compose').value, env: $('env').value}));
    await refreshList(); message('Gespeichert. Mit „Prüfen“ kannst du die Konfiguration validieren.');
  } catch (error) { message(error.message, true); }
  finally { busy = false; renderControls(); }
});
async function followJob(id) {
  let failures = 0;
  for (;;) {
    let job;
    try { job = await api('jobs/' + id); failures = 0; }
    catch (error) { if (++failures >= 5 || /nicht gefunden|abgelaufen/.test(error.message)) throw error; await new Promise(resolve => setTimeout(resolve, 2000)); continue; }
    $('job-status').textContent = job.name + ' · ' + job.action + (job.state === 'running' ? ' · läuft …' : ' · Exit ' + job.code);
    if (job.state !== 'running') {
      $('output').textContent = job.output || (job.code === 0 ? 'Erfolgreich abgeschlossen.' : 'Vorgang fehlgeschlagen.');
      message(job.code === 0 ? 'Vorgang abgeschlossen.' : 'Vorgang fehlgeschlagen. Siehe Ausgabe.', job.code !== 0);
      return;
    }
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
}
document.querySelectorAll('[data-action]').forEach(button => button.addEventListener('click', async () => {
  const action = button.dataset.action;
  if (action === 'down' && !confirm('Container und Compose-Netzwerke dieses Projekts entfernen? Benannte Volumes bleiben erhalten.')) return;
  busy = true; renderControls(); message('Vorgang läuft …'); $('output').textContent = 'Ausgabe wird nach Abschluss angezeigt (maximal 10 Minuten).';
  try { const job = await api('projects/' + encodeURIComponent(selected) + '/actions', {action}); await followJob(job.id); }
  catch (error) { message(error.message + ' Bei Verbindungsabbruch kann der Vorgang weiterlaufen. Oberfläche neu laden.', true); }
  finally { busy = false; renderControls(); }
}));
(async () => {
  newProject();
  try {
    const data = await refreshList();
    if (data.active_job) {
      busy = true; renderControls(); message('Laufender Vorgang wird wieder verbunden …');
      try { await followJob(data.active_job); } finally { busy = false; renderControls(); }
    }
  } catch (error) { message(error.message, true); }
})();
