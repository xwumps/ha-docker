# ha-docker · Compose Studio für Home Assistant OS

Eine eigene Home-Assistant-App (früher Add-on) für **Docker Compose V2** auf dem bestehenden HA-OS-Host. Mit deutscher Oberfläche, Compose-YAML-Editor, `.env`, Validierung, Start/Anwenden, Stoppen, Neustarten, Image-Download, Status und Logs. Mehrere unabhängige Projekte bilden deine Docker-Umgebungen auf diesem Host.

**Version 0.1.0 ist experimentell.** Sie ist kein offizielles Home-Assistant-Produkt. Der Container wird bei der Installation auf deinem Gerät gebaut; du musst keine Images selbst veröffentlichen. Unterstützt werden `amd64` (übliche Intel-/AMD-Laptops) und `aarch64`.

## Installation über dieses Repository

1. In Home Assistant **Einstellungen → Apps → App-Store → ⋮ → Repositories** öffnen. In älteren Versionen heißen die Menüpunkte „Add-ons“ und „Add-on-Store“.
2. Diese Repository-URL hinzufügen:

   ```text
   https://github.com/xwumps/ha-docker
   ```

3. „Compose Studio“ im Store öffnen und **Installieren**. Das erste Bauen benötigt Internet und kann einige Minuten dauern.
4. Den **Schutzmodus dieser App ausschalten**, damit sie auf die Docker-Engine zugreifen kann.
5. **Starten → Weboberfläche öffnen**. Optional „In der Seitenleiste anzeigen“ aktivieren.

Falls die App nach dem Hinzufügen nicht erscheint: Im Store-Menü „Nach Updates suchen“ wählen und die Seite neu laden. Die App ist als experimentell gekennzeichnet; Docker- und Browserprüfungen sind im [Prüfbericht](TESTREPORT.md) beschrieben. Eine Installation direkt unter HA OS ist noch zu bestätigen.

## Installation direkt aus der ZIP

1. ZIP entpacken. Den gesamten Ordner `compose_studio` in den lokalen App-Ordner **`/addons/compose_studio`** deines HA-OS-Systems kopieren. Das ist der Ordner für lokale Apps, nicht `/config/custom_components` und nicht ein Ordner auf deinem normalen PC. Mit der Samba-App kannst du normalerweise die Freigabe `addons` öffnen; alternativ eine bereits eingerichtete SSH-/Dateiverwaltungs-App verwenden.
2. In Home Assistant **Einstellungen → Apps → App-Store** öffnen. In älteren Versionen heißen diese Punkte „Add-ons“ und „Add-on-Store“. Im Menü **⋮ → Nach Updates suchen** die lokalen Apps neu einlesen. Falls nötig die Seite neu laden.
3. Unter **Lokale Apps** „Compose Studio“ öffnen und **Installieren**. Beim ersten Mal braucht das Gerät Internet für die Docker-Basisimages.
4. Den **Schutzmodus dieser App ausschalten**. Das ist für `docker_api: true` notwendig. Die restlichen Home-Assistant-Einstellungen müssen dafür nicht geändert werden.
5. **Starten → Weboberfläche öffnen**. Optional „In der Seitenleiste anzeigen“ und „Beim Booten starten“ aktivieren.

Falls die Installation scheitert, zuerst das Supervisor-Protokoll ansehen. Für Startprobleme das Protokoll der App öffnen. „Docker nicht erreichbar“ deutet insbesondere auf den noch aktivierten Schutzmodus hin.

## Eigenes Repository / Fork

Du kannst stattdessen den **Inhalt dieses Repository-Ordners** in ein eigenes GitHub-/Git-Repository hochladen. Im Repository-Hauptverzeichnis müssen `repository.yaml` und der Ordner `compose_studio/` liegen. Danach dessen echte Git-Repository-URL unter **App-Store → ⋮ → Repositories** hinzufügen. Die App wird weiterhin lokal gebaut.

Die Download-URL einer ZIP gehört nicht in den Home-Assistant-Repository-Dialog; verwende die Git-Repository-URL. Ein Home-Assistant-Community-Store-Eintrag oder HACS ist dafür nicht nötig. Beim Veröffentlichen eines Forks die Links in `repository.yaml` und `compose_studio/config.yaml` anpassen.

## Erstes Projekt

1. „Neu“ wählen, z. B. `webtest` als Namen eintragen und die mitgelieferte nginx-Vorlage speichern.
2. In `.env` steht `WEB_PORT=8090`. Falls dieser Port belegt ist, einen anderen freien Port wählen und erneut speichern.
3. „Prüfen“ und anschließend „Start / Anwenden“ drücken.
4. Unter `http://<IP-DEINES-HA-LAPTOPS>:8090` erreichst du den Webserver. `8090` ist der Port deines Beispielcontainers; Compose Studio selbst öffnet keinen Host-Port.
5. Mit „Status“ und „Logs“ den Zustand kontrollieren. Die Ausgabe erscheint nach Abschluss des Vorgangs, maximal nach zehn Minuten. Es gibt keinen interaktiven Terminalzugriff.

Die App verwendet tatsächlich `docker compose` V2, kein simuliertes Compose und keinen zweiten Docker-Daemon. YAML-Änderungen werden erst mit „Start / Anwenden“ wirksam. Für ein Image-Update „Images laden“ und anschließend „Start / Anwenden“ ausführen. Feste Image-Tags werden dabei nur aktualisiert, wenn der Herausgeber den Tag verändert hat; einen neuen Versions-Tag musst du selbst ins YAML eintragen.

## Dateien, Volumes und Backups

Die App speichert jedes Projekt in ihrem persistenten `/data/stacks/<name>/` mit `compose.yaml` und `.env`. Der tatsächliche Host-Pfad wird beim Start über Docker ermittelt und in der Oberfläche angezeigt. Die App bildet diesen Pfad intern ab, damit relative Bind-Mounts wie `./daten:/var/lib/mein-dienst` auf das richtige Verzeichnis des Hosts zeigen. Es gibt keinen hart codierten `/mnt/data/...`-Pfad.

Die UI bearbeitet nur `compose.yaml` und `.env`. Zusätzliche Dateien und Build-Kontexte lassen sich in Version 0.1.0 **nicht hochladen**. Für den Einstieg deshalb fertige Images und benannte Docker-Volumes oder relative Datenverzeichnisse verwenden. Absolute Bind-Pfade in eigenen Compose-Dateien beziehen sich auf den HA-OS-Host. Ein Pfad wie `/config` in einer anderen App ist nicht automatisch der richtige Host-Pfad für einen Compose-Container.

- „Stoppen“ lässt Container und Daten bestehen.
- „Container entfernen“ führt `docker compose down` aus, **ohne** `--volumes` und ohne globales Pruning. Benannte Volumes bleiben erhalten. Verwende für wichtige Daten benannte Volumes oder Bind-Mounts; anonyme Volumes werden bei einem späteren `up` nicht zuverlässig wiederverwendet. Daten nur in der beschreibbaren Container-Schicht gehen beim Entfernen verloren.
- **Ein Stoppen oder Deinstallieren der App stoppt deine Compose-Projekte nicht.** Vor einer Deinstallation die gewünschten Projekte stoppen/entfernen. `.env` und YAML rechtzeitig kopieren.
- Die App wird beim HA-Start gestartet, wenn „Beim Booten starten“ aktiv ist. Der automatische Neustart deiner Container wird durch deren Compose-`restart:`-Einstellung bestimmt. Compose Studio führt beim Start nicht automatisch `up` für alle Projekte aus.
- Ein Home-Assistant-Backup mit dieser App enthält deren `/data` und damit YAML, `.env` und dort gespeicherte relative Bind-Daten. **Benannte Docker-Volumes und beliebige externe Host-Verzeichnisse gehören nicht automatisch dazu.** Für Datenbanken konsistente, anwendungsspezifische Backups anlegen. Ein laufender Compose-Dienst wird für ein HA-App-Backup nicht automatisch gestoppt.
- Docker-Images, Netzwerke und benannte Volumes liegen außerhalb der App-Daten. HA-Wiederherstellung stellt daraus keine laufenden Compose-Dienste wieder her; Images und Container werden anschließend mit „Start / Anwenden“ neu angelegt. Verfügbare Anwendungsdaten separat wiederherstellen.

## Zugriff und Grenzen

Docker-Socket-Zugriff entspricht weitreichender Kontrolle über den Host, einschließlich Home Assistant. Auch ein read-only gemounteter Socket erlaubt schreibende Docker-API-Aufrufe. Deshalb Schutzmodus gezielt nur für diese App ausschalten und nur vertrauenswürdige Compose-Projekte verwenden. Diese App ist keine Sandbox für fremde Compose-Dateien.

Die Oberfläche ist ausschließlich über Home Assistant Ingress erreichbar. Sie nimmt nur Verbindungen von der dokumentierten Supervisor-IP `172.30.32.2` an. API-Aufrufe benötigen zusätzlich einen Sitzungstoken gegen fremde Browseranfragen. Keine zusätzliche Anmeldung, kein öffentlich freigegebener Verwaltungsport. Wer Zugang zur Oberfläche hat, kann Docker mit Host-Rechten verwenden; die Seitenleiste wird nur Administratoren angezeigt.

Die App richtet Befehle auf ihre eigenen Projekte mit Namen `cs_<projekt>`; sie bietet keine globale Liste oder Löschfunktion für HA-Container. Eigene Compose-Dateien können jedoch selbst fremde Ressourcen referenzieren, etwa über `external`, `container_name`, `privileged` oder Host-Bind-Mounts. Der Projekt-Präfix ist keine Sicherheitsgrenze.

Es gibt einen Docker-Endpunkt: den lokalen HA-OS-Host. Remote-Docker-Endpunkte, Git-Synchronisierung, interaktive Shells, Dateiuploads und eine automatische Aktualisierung aller Images sind nicht enthalten. Keine globale Docker-Bereinigung ausführen: Supervisor und Home Assistant teilen sich diese Engine. Eigene Container können dieselben Host-Ports, Arbeitsspeicher und Speicherplatz belegen wie Home Assistant.

## Entwicklung und Prüfung

```sh
python3 -m unittest discover -s tests -v
docker build -t compose-studio:dev compose_studio
```

Der Server benötigt nur die Python-Standardbibliothek. Die Docker-CLI und das Compose-V2-Plugin stammen aus dem offiziellen `docker:28.5.2-cli`-Image. Kein Docker-in-Docker und keine Laufzeitinstallation auf dem HA-Host. `tests/integration.py` prüft den Container mit einem simulierten Ingress-Proxy und einer echten lokalen Docker-Engine; es startet und entfernt ausschließlich eigens angelegte Testressourcen.

## Offizielle Referenzen

- [Home Assistant: App-Konfiguration, docker_api und Schutzmodus](https://contributors.home-assistant.io/apps/reference/configuration/)
- [Home Assistant: Ingress und erlaubte Supervisor-IP](https://contributors.home-assistant.io/apps/guides/ingress/)
- [Docker: Compose-Dokumentation](https://docs.docker.com/compose/)
