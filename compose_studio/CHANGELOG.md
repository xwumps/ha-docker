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
