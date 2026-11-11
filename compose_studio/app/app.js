'use strict';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="compose-token"]').content;
const example = 'services:\n  web:\n    image: nginx:1.28-alpine\n    restart: unless-stopped\n    ports:\n      - "${WEB_PORT:-8090}:80"\n    mem_limit: 128m\n    cpus: 0.5\n';
const fields = ['name', 'compose', 'env'];
let selected = null, dirty = false, busy = false, saved = false;
let mode = 'compose', nativeSelected = null, nativeDirty = false, nativeSaved = false;
const nativeText = ['image','entrypoint','network','user','workdir','hostname','memory','cpus','dockerfile','target','restart','pull_policy'];
const nativeLists = ['ports','mounts','cap_add','cap_drop','devices','add_hosts','dns','tmpfs'];
const nativeMaps = ['env','build_args','labels'];
const nativeChecks = ['build','read_only','privileged','init'];
function message(text, error = false) { $('message').textContent = text; $('message').className = error ? 'error' : ''; }
function renderControls() {
  document.querySelectorAll('button').forEach(button => {
    button.disabled = busy || (!!button.dataset.action && (!saved || dirty)) || (!!button.dataset.nativeAction && (!nativeSaved || nativeDirty));
  });
  fields.forEach(id => { $(id).disabled = busy || (id === 'name' && saved); });
  document.querySelectorAll('form input').forEach(field => { field.disabled = busy; });
  document.querySelectorAll('#docker-view input, #docker-view textarea, #docker-view select').forEach(field => { field.disabled = busy; });
  $('docker-name').disabled = busy || nativeSaved;
  $('docker-image').disabled = busy || $('docker-build').checked;
  $('docker-dirty').textContent = nativeDirty ? 'Ungespeichert' : nativeSaved ? 'Gespeichert' : 'Entwurf';
  $('dirty').textContent = dirty ? 'Ungespeichert' : saved ? 'Gespeichert' : 'Entwurf';
}
async function api(path, body) {
  const response = await fetch('api/' + path, {
    signal: AbortSignal.timeout(180000),
    method: body === undefined ? 'GET' : 'POST',
    headers: {'X-Compose-Token': token, ...(body === undefined ? {} : {'Content-Type': 'application/json'})},
    ...(body === undefined ? {} : {body: JSON.stringify(body)}),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Anfrage fehlgeschlagen.');
  return data;
}
function canLeave() { return !(mode === 'docker' ? nativeDirty : dirty) || confirm('Ungespeicherte Änderungen verwerfen?'); }
function markDirty() { dirty = true; renderControls(); }
fields.forEach(id => $(id).addEventListener('input', markDirty));
window.addEventListener('beforeunload', event => { if (dirty || nativeDirty || busy) { event.preventDefault(); event.returnValue = ''; } });
for (const id of ['compose', 'env']) $(id).addEventListener('keydown', event => {
  if (event.key === 'Tab') {
    event.preventDefault(); const field = event.target, start = field.selectionStart, end = field.selectionEnd;
    field.setRangeText('  ', start, end, 'end'); markDirty();
  }
});
async function refreshList() {
  const data = await api('projects');
  $('root').textContent = data.host_root;
  $('version').textContent = 'Docker · Compose ' + data.compose_version;
  $('projects').replaceChildren();
  data.projects.forEach(name => {
    const button = document.createElement('button'); button.textContent = name;
    if (mode === 'compose' && name === selected) button.className = 'selected';
    button.addEventListener('click', () => { if (canLeave()) load(name); });
    $('projects').append(button);
  });
  if (!data.projects.length) $('projects').textContent = 'Noch keine Projekte.';
  await refreshDockerList(); renderControls(); return data;
}
function fill(data) {
  showMode('compose'); nativeDirty = false;
  selected = data.name; saved = true; dirty = false;
  $('name').value = data.name; $('compose').value = data.compose; $('env').value = data.env;
  $('title').textContent = data.name;
  $('location').textContent = 'Projektdateien: ' + data.host_path + ' · Volume-Daten: ' + data.storage_path + ' · Compose-Projekt: ' + data.project_name;
  $('files-panel').hidden = false;
  renderControls();
}
async function load(name) {
  busy = true; renderControls(); message('');
  try { fill(await api('projects/' + encodeURIComponent(name))); await refreshList(); await refreshFiles(); }
  catch (error) { message(error.message, true); }
  finally { busy = false; renderControls(); }
}
function newProject() {
  if (!canLeave()) return;
  showMode('compose'); nativeDirty = false;
  selected = null; saved = false; dirty = false;
  $('name').value = ''; $('compose').value = example; $('env').value = 'WEB_PORT=8090\n';
  $('title').textContent = 'Neues Projekt'; $('location').textContent = 'Speichere zuerst dein Projekt.';
  $('files-panel').hidden = true;
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
    await refreshFiles();
  } catch (error) { message(error.message, true); }
  finally { busy = false; renderControls(); }
});
async function refreshFiles() {
  if (!selected) return;
  const data = await api('projects/' + encodeURIComponent(selected) + '/files');
  $('file-list').replaceChildren();
  data.files.forEach(path => { const item = document.createElement('li'); item.textContent = path; $('file-list').append(item); });
}
function encodedFile(file, limit) {
  if (!file || file.size > limit) return Promise.reject(new Error('Keine Datei gewählt oder Datei zu groß.'));
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.split(',')[1]);
    reader.onerror = () => reject(new Error('Datei konnte nicht gelesen werden.'));
    reader.readAsDataURL(file);
  });
}
$('open-install').addEventListener('click', () => { if (mode === 'docker' && !canLeave()) return; showMode('compose'); nativeDirty = false; $('install-panel').open = true; $('install-panel').scrollIntoView({behavior:'smooth', block:'start'}); });
async function importProject(data) {
  if (!canLeave()) return;
  busy = true; renderControls(); message('Projekt wird vorbereitet …');
  try {
    fill(await api('import', data)); await refreshList(); await refreshFiles();
    $('install-panel').open = false;
    message(data.kind === 'jotion' ? 'Jotion ist vorbereitet. „Start / Anwenden“ lädt die Images und startet alle Dienste. Den Master Key aus .env zusätzlich sicher aufbewahren.' : 'Importiert. .env prüfen, dann „Prüfen“ und „Start / Anwenden“.');
  } catch (error) { message(error.message, true); }
  finally { busy = false; renderControls(); }
}
$('jotion-form').addEventListener('submit', event => {
  event.preventDefault();
  importProject({kind:'jotion', name:$('jotion-name').value.trim(), version:$('jotion-version').value.trim().replace(/^v/,''), public_url:$('jotion-url').value.trim(), port:Number($('jotion-port').value)});
});
$('archive-form').addEventListener('submit', async event => {
  event.preventDefault();
  try { await importProject({kind:'archive',name:$('import-name').value.trim(),archive:await encodedFile($('archive').files[0],12*1024*1024)}); }
  catch (error) { message(error.message,true); }
});
$('extra-file').addEventListener('change', () => { if (!$('extra-path').value && $('extra-file').files[0]) $('extra-path').value = $('extra-file').files[0].name; });
$('file-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (!saved || busy) return;
  busy = true; renderControls();
  try {
    await api('projects/'+encodeURIComponent(selected)+'/files',{path:$('extra-path').value.trim(),content:await encodedFile($('extra-file').files[0],2*1024*1024)});
    await refreshFiles(); message('Zusatzdatei gespeichert. Mit „Start / Anwenden“ Änderungen übernehmen.');
  } catch (error) { message(error.message,true); }
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

function showMode(next) {
  mode = next; $('compose-view').hidden = next !== 'compose'; $('docker-view').hidden = next !== 'docker';
  document.querySelectorAll('nav button').forEach(button => button.classList.remove('selected'));
}
function shellQuote(value) { return /^[A-Za-z0-9_/@.:=-]+$/.test(value) ? value : "'" + value.replaceAll("'", "'\\''") + "'"; }
function fillNative(data, persisted = true) {
  showMode('docker'); dirty = false;
  nativeSelected = data.name || null; nativeSaved = persisted; nativeDirty = false;
  const config = data.config;
  $('docker-name').value = data.name || '';
  nativeText.forEach(key => {
    const field = $('docker-' + key), value = config[key] ?? ({restart:'unless-stopped', network:'bridge', dockerfile:'Dockerfile', pull_policy:'missing'}[key] || '');
    if (field.tagName === 'SELECT' && !Array.from(field.options).some(option => option.value === value)) field.add(new Option(value, value));
    field.value = value;
  });
  nativeLists.forEach(key => { $('docker-' + key).value = (config[key] || []).join('\n'); });
  nativeMaps.forEach(key => { $('docker-' + key).value = Object.entries(config[key] || {}).map(([k,v]) => k + '=' + v).join('\n'); });
  nativeChecks.forEach(key => { $('docker-' + key).checked = !!config[key]; });
  $('docker-command').value = Array.isArray(config.command) ? config.command.map(shellQuote).join(' ') : config.command || '';
  $('docker-title').textContent = persisted ? data.name : 'Neuer Docker-Container';
  $('docker-location').textContent = data.host_path ? 'Konfiguration: ' + data.host_path + ' · Kontext: ' + data.context_path + ' · Docker-Name: ' + data.container_name : 'Konfiguration zuerst speichern.';
  $('docker-files-panel').hidden = !persisted;
  $('docker-files').replaceChildren();
  (data.files || []).forEach(path => { const item = document.createElement('li'); item.textContent = path; $('docker-files').append(item); });
  renderControls();
}
function newNative() {
  if (!canLeave()) return;
  fillNative({name:'',config:{image:'nginx:alpine',ports:['8090:80']}},false);
  message(''); $('docker-name').focus();
}
$('new-docker').addEventListener('click', newNative);
async function refreshDockerList() {
  const data = await api('docker/containers');
  $('docker-list').replaceChildren();
  data.containers.forEach(container => {
    const button = document.createElement('button'); button.textContent = container.name;
    if (mode === 'docker' && container.name === nativeSelected) button.className = 'selected';
    button.addEventListener('click', () => { if (canLeave()) loadNative(container.name); });
    $('docker-list').append(button);
  });
  if (!data.containers.length) $('docker-list').textContent = 'Noch keine Container.';
}
async function loadNative(name) {
  busy = true; renderControls(); message('');
  try { fillNative(await api('docker/containers/' + encodeURIComponent(name))); await refreshList(); }
  catch (error) { message(error.message,true); }
  finally { busy = false; renderControls(); }
}
function nativeForm() {
  const config = {};
  nativeText.forEach(key => { config[key] = $('docker-'+key).value.trim(); });
  nativeLists.forEach(key => { config[key] = $('docker-'+key).value.split('\n').map(v => v.trim()).filter(Boolean); });
  nativeMaps.forEach(key => {
    config[key] = {};
    $('docker-'+key).value.split('\n').forEach(line => {
      if (!line.trim() || line.trimStart().startsWith('#')) return;
      const split = line.indexOf('=');
      if (split < 1) throw new Error('Variablen und Labels als NAME=WERT angeben.');
      config[key][line.slice(0,split).trim()] = line.slice(split+1);
    });
  });
  nativeChecks.forEach(key => { config[key] = $('docker-'+key).checked; });
  config.command = $('docker-command').value;
  return config;
}
const nativeEditIds = [...nativeText,...nativeLists,...nativeMaps,...nativeChecks,'command','name'];
for (const key of nativeEditIds) $('docker-'+key).addEventListener('input', () => { nativeDirty=true; renderControls(); });
$('parse-run').addEventListener('click', async () => {
  if (!canLeave()) return;
  busy=true; renderControls();
  try {
    const parsed=await api('docker/parse',{command:$('docker-run').value});
    fillNative(parsed,false); nativeDirty=true; $('run-panel').open=false;
    message('Docker-Befehl übernommen. Einstellungen prüfen, speichern und „Start / Anwenden“ wählen.');
  } catch (error) { message(error.message,true); }
  finally { busy=false; renderControls(); }
});
$('docker-save').addEventListener('click', async () => {
  const name=$('docker-name').value.trim();
  if(!/^[a-z][a-z0-9_-]{0,39}$/.test(name)){message('Containername: mit a–z beginnen, maximal 40 Zeichen aus a–z, 0–9, _ und -.',true);return;}
  let config;
  try { config=nativeForm(); } catch(error) { message(error.message,true); return; }
  busy=true; renderControls();
  try {
    if (!nativeSaved && (await api('docker/containers')).containers.some(c=>c.name===name)) throw new Error('Name bereits vorhanden. Container links öffnen.');
    fillNative(await api('docker/containers/'+encodeURIComponent(name),{config}));
    await refreshList(); message('Container-Konfiguration gespeichert. „Start / Anwenden“ startet sie direkt mit Docker.');
  } catch(error) { message(error.message,true); }
  finally { busy=false; renderControls(); }
});
$('docker-archive-form').addEventListener('submit', async event => {
  event.preventDefault(); if(!canLeave())return;
  const name=$('docker-import-name').value.trim(), file=$('docker-archive').files[0];
  busy=true; renderControls(); message('Dockerfile-Projekt wird importiert …');
  try {
    fillNative(await api('docker/import',{name,dockerfile:$('docker-import-dockerfile').value.trim()||'Dockerfile',archive:await encodedFile(file,12*1024*1024)}));
    $('docker-import-panel').open=false; await refreshList();
    message('Dockerfile-Projekt importiert. Ports und Einstellungen prüfen, speichern und „Start / Anwenden“ wählen.');
  }catch(error){message(error.message,true);}finally{busy=false;renderControls();}
});
$('docker-extra-file').addEventListener('change',()=>{if(!$('docker-extra-path').value&&$('docker-extra-file').files[0])$('docker-extra-path').value=$('docker-extra-file').files[0].name;});
$('docker-file-form').addEventListener('submit',async event=>{
  event.preventDefault(); if(!nativeSaved||busy)return;
  const file=$('docker-extra-file').files[0],path=$('docker-extra-path').value.trim();
  busy=true;renderControls();
  try {
    const data=await api('docker/containers/'+encodeURIComponent(nativeSelected)+'/files',{path,content:await encodedFile(file,2*1024*1024),...($('docker-extra-executable').checked?{executable:true}:{})});
    $('docker-files').replaceChildren(); data.files.forEach(path=>{const li=document.createElement('li');li.textContent=path;$('docker-files').append(li);});
    message('Datei gespeichert. Für geänderten Build-Code „Image bauen“, danach „Start / Anwenden“.');
  }catch(error){message(error.message,true);}finally{busy=false;renderControls();}
});
document.querySelectorAll('[data-native-action]').forEach(button=>button.addEventListener('click',async()=>{
  const action=button.dataset.nativeAction;
  if(action==='remove'&&!confirm('Diesen Docker-Container entfernen? Konfiguration und persistente Daten bleiben erhalten.'))return;
  busy=true;renderControls();message('Docker-Vorgang läuft …');$('output').textContent='Ausgabe wird nach Abschluss angezeigt (maximal 10 Minuten).';
  try {
    const job=await api('docker/containers/'+encodeURIComponent(nativeSelected)+'/actions',{action,command:action==='exec'?$('docker-exec').value:''});
    await followJob(job.id);
  }catch(error){message(error.message+' Bei Verbindungsabbruch kann der Vorgang weiterlaufen.',true);}finally{busy=false;renderControls();}
}));

(async () => {
  newNative();
  try {
    const data = await refreshList();
    if (data.active_job) {
      busy = true; renderControls(); message('Laufender Vorgang wird wieder verbunden …');
      try { await followJob(data.active_job); } finally { busy = false; renderControls(); }
    }
  } catch (error) { message(error.message, true); }
})();
