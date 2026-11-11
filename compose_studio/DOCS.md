# Compose Studio

Repository: [xwumps/ha-docker](https://github.com/xwumps/ha-docker). Zum Hinzufügen im App-Store die URL `https://github.com/xwumps/ha-docker` verwenden.

1. Schutzmodus dieser App deaktivieren, anschließend starten.
2. „Weboberfläche öffnen“ wählen.
3. Projekt benennen, Compose-YAML und `.env` speichern, „Prüfen“, dann „Start / Anwenden“.

Die App steuert die vorhandene Docker-Engine deines Home-Assistant-OS-Geräts mit Docker Compose V2. Sie braucht dadurch weitreichende Rechte auf dem Host. Nur vertrauenswürdige Compose-Dateien verwenden.

Die Vorlage startet nginx auf dem in `.env` eingestellten Host-Port 8090. Bei einem Port-Konflikt `WEB_PORT` ändern. Containerdienste sind über ihre eigenen Ports erreichbar; die App-Oberfläche läuft über Home Assistant Ingress.

„Images laden“ lädt die Images; danach „Start / Anwenden“ zum Aktualisieren der Container. „Stoppen“ behält Container. „Container entfernen“ entfernt Container und Projektnetzwerke, behält benannte Volumes. Die beschreibbare Container-Schicht geht beim Entfernen verloren.

**Ein Stopp oder Deinstallieren dieser App stoppt deine Projekte nicht.** Neustarts nach einem Host-Reboot bestimmt `restart:` im Compose-YAML. Benannte Docker-Volumes und externe Bind-Mounts sind nicht automatisch im HA-App-Backup enthalten. `.env` und YAML liegen im persistenten privaten App-Verzeichnis; dessen Host-Pfad zeigt die Oberfläche an.

Die Oberfläche bearbeitet YAML und `.env`; zusätzliche Dateien/Build-Kontexte können hier noch nicht hochgeladen werden. Logs sind auf die letzten 200 Zeilen pro Dienst begrenzt und erscheinen nach Abschluss des Abrufs. Ein Vorgang zur Zeit; laufende Vorgänge lassen sich nach einem Neuladen der Oberfläche wieder verbinden, aber nicht über einen Neustart der App hinweg.

Wenn die App nicht startet: App-Protokoll lesen und Schutzmodus prüfen. Vollständige Installation, Repository-Veröffentlichung, Datenpfade, Backups und Grenzen stehen in der README des Repositorys.
