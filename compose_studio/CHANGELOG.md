# 0.3.1

- Bevorzugt den vom HA-Supervisor eingebundenen Socket `/run/docker.sock`; unterstützt weiterhin `/var/run/docker.sock`.
- Prüft auf tatsächliche Unix-Sockets und unterscheidet einen fehlenden Mount von einer fehlgeschlagenen Daemon-Verbindung.
- Kurze, konkrete Startanleitung bei fehlendem Docker-Zugriff statt wiederholter Python-Tracebacks.
- Zusätzliche Socket-Tests mit echten Unix-Sockets und Docker-Proben für HA-Mount, Legacy-Fallback und fehlenden Mount.

# 0.3.0

- Neuer nativer Docker-Bereich ohne Compose-Datei: Formulare, docker run-Import, Container starten/stoppen/neustarten/entfernen, Status, Logs und nicht interaktives docker exec.
- Dockerfile-Kontexte als Archiv importieren; Dateien, Build-Argumente und Build-Targets verwalten; Images mit Docker Buildx bauen.
- Persistente native Volumes einschließlich automatisch zugeordneter Image-VOLUME-Pfade im App-Speicher.
- Native Container werden zusammen mit Compose-Projekten für HA-Backups und App-Stopps angehalten und anschließend fortgesetzt.
- Eigene/lokale native Images werden für HA-Backups exportiert und beim Restore geladen; Wiederanlauf nutzt die zuletzt angewendete Konfiguration.
- Anzeigename jetzt „Docker Studio“; bestehender Slug `compose_studio` und bestehende Compose-Projekte bleiben nutzbar.

# 0.2.0

- Jotion-Assistent: Release-Paket, Zusatzdateien, feste Image-Version und automatisch erzeugte Schlüssel ohne Shellskript-Ausführung.
- Import von ZIP/TAR/TAR.GZ-Projekten und Upload zusätzlicher Dateien.
- Verwaltete lokale Docker-Volumes mit Nutzdaten im persistenten App-Verzeichnis.
- HA-Backup-Hooks: Schreibsperre, geordnetes Stoppen und Wiederanlauf der zuvor aktiven Projekte.
- Wiederherstellung mit auf den Zielhost angepassten Pfaden und Volume-Hüllen.
- Übernahme bestehender lokaler Volumes mit erhaltenen Eigentümern und ohne Löschen der Originalvolumes.
- **Verhaltensänderung:** Ein App-Stopp stoppt jetzt auch die laufenden Projekte und merkt sich den Wiederanlauf.
- Image-basierter Betrieb mit `--no-build`; nicht automatisch sicherbare externe/anonyme Speicherformen werden abgewiesen.

# 0.1.0

- Experimentelle erste Version für HA OS auf amd64 und aarch64.
- Docker Compose V2 mit YAML- und .env-Editor und Home Assistant Ingress.
- Validieren, Starten/Anwenden, Stoppen, Neustarten, Images laden, Status und Logs.
- Automatische Erkennung des persistenten Datenpfads für relative Bind-Mounts.
