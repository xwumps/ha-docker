# Prüfstand für Version 0.3.1

Geprüft am 11. November 2026 in einer Linux-amd64-Cloud-Entwicklungsumgebung mit echter lokaler Docker-Engine. **Nicht direkt auf Home Assistant OS oder aarch64 installiert/getestet.** Die App bleibt experimentell.

## Hotfix 0.3.1: Docker-Socket

Der Nutzerbericht zeigte beim Start `Cannot connect to the Docker daemon at unix:///var/run/docker.sock`. Aus diesem Log allein lässt sich nicht erkennen, ob der Schutzmodus noch aktiv war, der Socket fehlte oder eine vorhandene Verbindung nicht erreichbar war. Der HA-Supervisor bindet laut aktuellem Quellcode `/run/docker.sock` nur bei `docker_api` und ausgeschaltetem Schutzmodus ein.

Für 0.3.1 wurden **37 Unit-Tests** ausgeführt: die 32 bestehenden Tests plus fünf Socket-Tests für HA-Pfad ohne Alias, Legacy-Fallback, reguläre Datei statt Socket, fehlenden Mount und eingebundenen, aber nicht erreichbaren Socket.

Zusätzlich mit echter lokaler Docker-Engine geprüft:

- Start ohne Socket: Exit 1 mit konkreter Schutzmodus-Anleitung und ohne Python-Traceback.
- Vollständiger App-Start mit HA-Mount `/run/docker.sock`, wobei `/var/run` absichtlich ein eigenständiges leeres Verzeichnis ist. Die Weboberfläche startet und weist direkte Verbindungen weiterhin mit 403 ab.
- Legacy-Fallback über `/var/run/docker.sock`: echte Docker-Verbindung und Erkennung des eigenen persistenten Datenpfads.

Ein Image wurde erfolgreich neu gebaut. Die folgenden umfangreichen Container-/Build-/Restore- und Browsernachweise stammen aus Version 0.3.0; diese Funktionen wurden durch den Hotfix nicht verändert. Ein direkter Installationstest von 0.3.1 auf dem Nutzergerät steht noch aus. Ein vom Supervisor nicht eingebundener Socket kann durch die App nicht selbst freigegeben werden.

Reproduktion: `python3 tests/socket_integration.py` nach dem Image-Build.

## Bestehende automatisierte Tests aus 0.3.0

**32 Python-Tests bestanden.** Bestehende Zugriffs-/Projektgrenzen, sicherer ZIP/TAR-Import, Pfad-/Symlink-/Hardlink-Grenzen, Größenbegrenzung, Jotion-Schlüssel, Volume-Migration und Restore-Pfade sowie zusätzliche native Docker-Prüfungen:

- docker run-Parser mit Ports, Variablen, Quotes, Mehrzeilenbefehlen, Neustartregeln und --mount; Host-Variablen werden nicht ausgewertet.
- Nicht unterstützte Flags, Host-Shell-Verkettungen, fremde Datenpfade, interne Labels und doppelte Mount-Ziele werden abgewiesen.
- Dockerfile-Archivimport ohne Compose, eigener Dockerfile-Pfad, erhaltene ausführbare Skriptrechte und Entfernen von Setuid-Bits.
- Upload über Symlink-Eltern wird abgewiesen; ausführbare Uploads und vorhandene Rechte bleiben korrekt.
- Native Befehle verwenden Docker container create; implizite Image-VOLUME-Ziele werden persistent zugeordnet.
- Fremde Container mit kollidierendem Namen können nicht entfernt werden und werden im Backup-Inventar nicht als eigene Container behandelt.
- Ein abgebrochener Create-Schritt ohne gestarteten Container blockiert kein Backup.
- Wiederanlauf verwendet die zuletzt angewendete native Konfiguration; offene Entwürfe werden nicht angewendet.
- Fehlgeschlagener Image-Export hinterlässt kein scheinbar fertiges Backup-Image.

## Echte Docker-Integration bestanden

- App-Image gebaut, Docker-CLI mit Compose **V2.40.3** und Buildx **v0.29.1** geprüft.
- Home-Assistant-Ingress nachgestellt: Quell-IP 172.30.32.2, verschachtelter URL-Präfix, direkter Zugriff abgewiesen.
- Compose-Regression: Validierung, Start, relative Bind-Mounts, .env-Interpolation, Status, Logs, Stop, Restart und Down mit erhaltenem Volume.
- Nativer docker run-Import über die HTTP-API; echter Container mit erreichbarem HTTP-Port, Variablen und benanntem persistentem Volume gestartet.
- Native Logs, Status, Stop/Restart und docker exec ausgeführt.
- Dockerfile-ZIP mit COPY eines ausführbaren entrypoint.sh und RUN dieses Skripts gebaut; Dateirechte im echten Build nachgewiesen. Container gestartet, Build-/Kontextdateien gelesen und implizites Image-VOLUME persistent verwendet.
- Eigenes Image als TAR im App-Datenordner gesichert.
- Backup-Hooks stoppen Compose- und native Container gemeinsam und sperren Änderungen; App-Daten als TAR gesichert und Dienste danach fortgesetzt.
- Danach Daten verändert, native Container entfernt und das selbst gebaute Image aus Docker entfernt.
- Backup in einen anderen Host-Datenpfad wiederhergestellt; Dockerfile im wiederhergestellten Kontext absichtlich ungültig gemacht, um einen zufällig erfolgreichen Neuaufbau auszuschließen.
- Wiederanlauf lädt das exakte eigene Image aus dem Backup, stellt Daten/implizite Volumes wieder her und verwendet den vorher angewendeten Variablenwert. Der gespeicherte, noch nicht angewendete Entwurf bleibt separat erhalten. Compose-Bind-Pfade werden ebenfalls angepasst.

## Browserprüfung

Chromium auf Desktop (1440 px) und Mobil (390 px): Native Standardansicht, docker run ins Formular übernehmen, speichern/starten, Logs, Sperre bei ungespeicherten Änderungen, erneutes Laden, Dockerfile-Archivimport, Build/Start und docker exec bestanden. Keine JavaScript-Seitenfehler, kein horizontaler Seitenüberlauf auf Mobil.

Zusätzlicher Browserlauf auf dem endgültigen Stand bestanden: eigener Dockerfile-Pfad `docker/Dockerfile`, ausführbares Archiv-Skript unter Image-USER 1000, ausführbarer Einzeldatei-Upload, expliziter Neubau und Anwenden, Logs und Desktop-/Mobilansicht. Keine JavaScript-Seitenfehler.

Compose-Browserablauf nach der Erweiterung ebenfalls bestanden: Archivimport, Zusatzdatei-Upload, Validierung, Speichern, Start, Logs und Desktop-/Mobilansicht.

## Nicht als bestanden zu werten

**Vollständiger Jotion-Start:** Beim Test der Version 0.2 wurde der Versuch durchgeführt, scheiterte aber beim Entpacken der offiziellen Container-Images mit `no space left on device`. Die Testumgebung hat insgesamt rund 8 GB und verwendet den speicherintensiven Docker-VFS-Treiber. Jotion-Datenbankmigrationen, Weboberfläche und der vollständige Jotion-Stack konnten in dieser Umgebung deshalb nicht abschließend geprüft werden. Das ist eine konkrete Testgrenze; ein erfolgreicher Komplettbetrieb wird nicht behauptet.

**Echter HA-Supervisor:** Die Hook-Reihenfolge wurde gegen den aktuellen Supervisor-Quellcode geprüft und mit Docker nachgestellt. Store-Erkennung, Installation, AppArmor, tatsächliche HA-Backup-Datei und deren Restore auf HA OS stehen noch aus. Ebenso aarch64 und reale Fremdprojekte mit anderen Speicheranforderungen.

## Reproduktion

```sh
python3 -m unittest discover -s tests -v
docker build -t compose-studio:dev compose_studio
KEEP_TEST_APP=1 python3 tests/integration.py
python3 tests/legacy_integration.py
```

Ohne `KEEP_TEST_APP=1` räumt `tests/integration.py` seine Testcontainer, -netzwerke und -volumes nach dem Lauf auf. Die Legacy-Prüfung benötigt die beibehaltene Test-App. Testnamen sind ausdrücklich für diese Prüfungen reserviert.

Der Nutzer-Laptop wurde nicht angesprochen. Projekt-Repository: [xwumps/ha-docker](https://github.com/xwumps/ha-docker).
