# Docker Studio 0.3

## Native Docker-Container

Unter „Docker-Container → Neu“ Image, Ports, Variablen und persistente Mounts eintragen. „Container speichern → Start / Anwenden“ startet direkt mit Docker, ohne Compose-Datei.

Alternativ unter „docker run-Befehl übernehmen“ einen einzelnen Befehl einfügen, ins Formular übernehmen, prüfen und speichern. Unbekannte Optionen werden gemeldet. Es gibt keinen Host-Shell- oder interaktiven Terminalzugriff.

Dockerfile-Projekte als ZIP/TAR importieren, Ports ergänzen und starten. Bei späteren Quellcode-Änderungen „Image bauen“ und anschließend „Start / Anwenden“. Dateien lassen sich im Kontext hochladen. Build-Target und Build-Argumente sind einstellbar.

Benannte native Volumes werden im App-Speicher verwaltet und zwischen nativen Containern geteilt, wenn der gleiche logische Name verwendet wird. Relative Bind-Pfade beziehen sich auf den eigenen Kontext. Implizite Image-Volumes werden automatisch persistent zugeordnet. Eigene gebaute bzw. nur lokal vorhandene Images werden zusätzlich als TAR für HA-Backups gespeichert.

## Compose / Jotion installieren

„Installieren / Importieren“ öffnen. Für Jotion Projektname, freien Port und Browser-Adresse des HA-Geräts eingeben, dann „Jotion vorbereiten“ und „Start / Anwenden“. Das Paket und sichere Schlüssel werden automatisch vorbereitet. Den Master Key aus `.env` zusätzlich separat aufbewahren.

Andere Apps als ZIP/TAR mit Compose-Datei und Zusatzdateien importieren. `.env` im Editor prüfen; weitere Dateien unter „Zusatzdateien im Projekt“ hochladen. Ein importiertes `.env.example` kann noch Platzhalter enthalten. Im Compose-Bereich werden fertige Container-Images benötigt; lokale Builds gibt es im nativen Dockerfile-Bereich. Host-Installationsskripte werden nicht ausgeführt.

## Backup und Daten

Normale lokale benannte Volumes werden unter dem persistenten App-Datenordner gespeichert. Relative Bind-Mounts innerhalb dieses Ordners sind ebenfalls enthalten. In Home Assistant ein Backup erstellen und **diese App auswählen**. Beim Backup werden die aktiven Projekte angehalten und danach wieder gestartet. Bei laufendem Compose-Vorgang schlägt der Backup-Vorlauf fehl; später erneut sichern.

Nach einer HA-Wiederherstellung setzt die App zuvor aktive Projekte mit den wiederhergestellten Daten fort. Registry-Images müssen vorhanden oder abrufbar sein. Gesicherte eigene native Images werden bei Bedarf aus dem App-Backup geladen. Ein Wiederanlauf nutzt die zuletzt angewendete native Konfiguration; offene Entwürfe werden dabei nicht übernommen. Externe Volumes, eigene Treiber und Host-Pfade außerhalb der App sind nicht automatisch sicherbar und werden abgewiesen.

**Neu ab 0.2: Ein App-Stopp stoppt auch die Projekte.** Beim nächsten App-Start werden zuvor aktive Projekte fortgesetzt. Vor einer Deinstallation YAML, Schlüssel und Daten sichern; das Löschen der App-Daten kann auch die verwalteten Volume-Nutzdaten entfernen.

Beim Upgrade von 0.1 werden normale lokale Volumes im gestoppten Zustand kopiert. Die Originalvolumes bleiben erhalten. Das braucht vorübergehend zusätzlichen Speicherplatz.

## Betrieb

Für Docker-Zugriff den Schutzmodus dieser App ausschalten. Nur vertrauenswürdige Compose-Projekte verwenden; die App besitzt weitreichende Host-Rechte. Die Oberfläche läuft über Home Assistant Ingress. Die eigentlichen Dienste erreichst du über ihre Compose-Ports.

„Images laden“ lädt Images der eingetragenen Tags, „Start / Anwenden“ übernimmt die Konfiguration. „Container entfernen“ behält persistente Daten. „Logs“ zeigt die letzten 200 Zeilen pro Dienst nach dem Abruf. Bei Problemen zuerst das App-Protokoll prüfen.

Version 0.3 ist experimentell. Installation, Datensicherung, Wiederherstellung und Grenzen: [README](https://github.com/xwumps/ha-docker#readme).
