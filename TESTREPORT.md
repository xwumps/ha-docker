# Prüfstand für Version 0.2.0

Geprüft am 11. November 2026 in einer Linux-amd64-Cloud-Entwicklungsumgebung mit echter lokaler Docker-Engine. **Nicht direkt auf einem Home-Assistant-OS-System oder auf aarch64 installiert/getestet.** Die App bleibt experimentell.

## Bestanden

- Docker-Image aus dem mitgelieferten Dockerfile gebaut; Compose **V2.40.3**.
- **18 Python-Tests**: bestehende Zugriffs-/Projektgrenzen sowie Archivimport mit Zusatzdateien, Pfadüberschreitungen, ZIP-Symlinks, TAR-Hardlinks, Größenprüfung vor dem Entpacken eines TAR-Mitglieds, reservierte Dateien, Datei-Upload über Symlink-Eltern, eindeutige Jotion-Schlüssel, Image-Pinning, lokale Volume-Speicherpfade, Abweisen externer/anonymer Speichervorgaben, Rücknahme eines teilweise gescheiterten Volume-Kopiervorgangs, Pfadwechsel bei Restore, prozessübergreifende Sperre und Backup-Marker.
- Echter Compose-Betrieb über simulierten HA-Ingress mit Quell-IP `172.30.32.2` und verschachteltem URL-Präfix: Validieren, Starten, Status, Logs, Stoppen, Neustarten und Entfernen der Container.
- Tatsächliches Schreiben durch einen relativen Bind-Mount und `.env`-Interpolation.
- Lokale Volume-Hülle mit Bind-Treiber: Nutzdaten liegen tatsächlich unter dem App-Datenpfad.
- Backup-Hooks in der Reihenfolge des Supervisors ausgeführt: Container gestoppt, Bearbeitung während des Backups abgewiesen, App-Daten als TAR gesichert und Projekte anschließend fortgesetzt.
- Wiederherstellung dieses App-Datenarchivs in einen **anderen Host-Datenpfad**: Volume-Inhalte und Bind-Dateien erhalten, neue Volume-Hüllen auf den neuen Pfad eingerichtet, `.env` erhalten und vorher aktives Projekt automatisch gestartet. Alte Docker-Volumes blieben beim Test absichtlich bestehen, damit ein fälschlicher Rückgriff auf diese auffällt.
- Übernahme eines echten alten Compose-Volumes: Dateiinhalt, UID 123, GID 456 und Modus 640 nach der Kopie erhalten. Änderung im neuen Speicher verändert das ursprüngliche Volume nicht.
- Geordneter App-Stopp mit zwei aktiven Projekten: beide gestoppt; neue App-Instanz setzt beide fort.
- Chromium, Desktop (1440 px) und Mobil (390 px): Archivimport, erhaltene Zusatzdateien, weiterer Datei-Upload, Validierung, Sperre bei ungespeicherten Änderungen, echter Start eines importierten Busybox-Projekts und Logs. Keine JavaScript-Seitenfehler; kein horizontaler Seitenüberlauf auf Mobil.
- Echtes Jotion-v1.0.1-Release-Paket heruntergeladen, GitHub-SHA256 geprüft, Caddyfile und Betriebsdateien übernommen, Schlüssel erzeugt und Image-Version eingetragen. HTTP-API-Import mit Cloud-CA-Vertrauen sowie Jotion-Einrichtung über das Browserformular geprüft; die erzeugte Konfiguration und Caddyfile sind anschließend wieder abrufbar.
- JavaScript-Syntax und App-/Repository-YAML geprüft.

## Nicht als bestanden zu werten

**Vollständiger Jotion-Start:** Der Versuch wurde durchgeführt, scheiterte aber beim Entpacken der offiziellen Container-Images mit `no space left on device`. Die Testumgebung hat insgesamt rund 8 GB und verwendet den speicherintensiven Docker-VFS-Treiber. Jotion-Datenbankmigrationen, Weboberfläche und der vollständige Jotion-Stack konnten in dieser Umgebung deshalb nicht abschließend geprüft werden. Das ist eine konkrete Testgrenze; ein erfolgreicher Komplettbetrieb wird nicht behauptet.

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
