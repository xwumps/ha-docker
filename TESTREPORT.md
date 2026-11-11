# Prüfstand für Version 0.1.0

Geprüft am 11. November 2026 in einer Linux-amd64-Entwicklungsumgebung mit echter lokaler Docker-Engine. **Nicht direkt auf einem Home-Assistant-OS-System oder auf aarch64 installiert/getestet.** Die App ist deshalb als experimentell gekennzeichnet.

## Bestanden

- Docker-Image erfolgreich aus dem mitgelieferten Dockerfile gebaut; `docker compose version` meldet **v2.40.3**.
- Sieben automatisierte Python-Tests: ungültige Projektnamen/Pfadüberschreitungen, Symlinks, Schreibsperre bei laufenden Jobs, Host-Pfad-Erhalt, Abbruch vor `up` bei ungültiger Compose-Konfiguration, Ablehnen direkter Verbindungen einschließlich gefälschtem Forwarded-Header, Sitzungstoken und Cross-Site-Schutz.
- Integration mit simuliertem Home-Assistant-Ingress: Proxy unter `172.30.32.2`, variablem URL-Präfix und echter Docker-Socket-Verbindung. Direkter Zugriff auf den App-Server wird abgewiesen.
- Echtes Busybox-Compose-Projekt erstellt, validiert, gestartet, Status und Logs abgefragt, gestoppt, neu gestartet und mit `down` entfernt.
- `.env`-Interpolation und tatsächliches Schreiben über einen relativen Bind-Mount am erwarteten Host-Pfad nachgewiesen.
- Benanntes Docker-Volume nach `down` weiterhin vorhanden.
- App-Container neu gestartet; Projekt-YAML und `.env` danach weiterhin lesbar.
- Browserprüfung mit Chromium: Laden unter Ingress-Präfix einschließlich CSS/JS, Speichern eines Projekts, Validieren mit echter Compose-CLI, Sperren von Aktionen bei ungespeicherten Änderungen und erneutes Laden der gespeicherten Werte. Keine JavaScript-Seitenfehler.
- Ansichten bei 1440 Pixeln und 390 Pixeln geprüft; bei 390 Pixeln kein horizontaler Seitenüberlauf.
- JavaScript-Syntax geprüft; Repository- und App-YAML erfolgreich eingelesen.

## Noch am Zielsystem zu prüfen

- Erkennung und Build durch den Home-Assistant-Supervisor.
- Schutzmodus-Schalter, Docker-Socket-Mount und AppArmor auf der jeweiligen HA-OS-Version.
- Echter Home-Assistant-Login/Ingress und App-Backup/-Wiederherstellung.
- aarch64-Laufzeit; Image-Pulls auf dem Heimnetz; reale Anwendungsprojekte.

Projekt-Repository: [xwumps/ha-docker](https://github.com/xwumps/ha-docker). Die Quellen sind für eine lokale Installation oder das Hinzufügen dieses Repositorys im App-Store vorbereitet. Es wurde kein Zugriff auf den Laptop des Nutzers hergestellt; die oben beschriebenen Docker- und Browserprüfungen fanden in der Entwicklungsumgebung statt.
