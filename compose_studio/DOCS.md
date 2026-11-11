# Compose Studio 0.2

## Installieren

„Installieren / Importieren“ öffnen. Für Jotion Projektname, freien Port und Browser-Adresse des HA-Geräts eingeben, dann „Jotion vorbereiten“ und „Start / Anwenden“. Das Paket und sichere Schlüssel werden automatisch vorbereitet. Den Master Key aus `.env` zusätzlich separat aufbewahren.

Andere Apps als ZIP/TAR mit Compose-Datei und Zusatzdateien importieren. `.env` im Editor prüfen; weitere Dateien unter „Zusatzdateien im Projekt“ hochladen. Ein importiertes `.env.example` kann noch Platzhalter enthalten. Es werden fertige Container-Images benötigt. Installationsskripte und lokale Builds werden nicht ausgeführt.

## Backup und Daten

Normale lokale benannte Volumes werden unter dem persistenten App-Datenordner gespeichert. Relative Bind-Mounts innerhalb dieses Ordners sind ebenfalls enthalten. In Home Assistant ein Backup erstellen und **diese App auswählen**. Beim Backup werden die aktiven Projekte angehalten und danach wieder gestartet. Bei laufendem Compose-Vorgang schlägt der Backup-Vorlauf fehl; später erneut sichern.

Nach einer HA-Wiederherstellung setzt die App zuvor aktive Projekte mit den wiederhergestellten Daten fort. Docker-Images müssen vorhanden oder abrufbar sein. Externe Volumes, eigene Treiber und Host-Pfade außerhalb der App sind nicht automatisch sicherbar und werden abgewiesen.

**Neu ab 0.2: Ein App-Stopp stoppt auch die Projekte.** Beim nächsten App-Start werden zuvor aktive Projekte fortgesetzt. Vor einer Deinstallation YAML, Schlüssel und Daten sichern; das Löschen der App-Daten kann auch die verwalteten Volume-Nutzdaten entfernen.

Beim Upgrade von 0.1 werden normale lokale Volumes im gestoppten Zustand kopiert. Die Originalvolumes bleiben erhalten. Das braucht vorübergehend zusätzlichen Speicherplatz.

## Betrieb

Für Docker-Zugriff den Schutzmodus dieser App ausschalten. Nur vertrauenswürdige Compose-Projekte verwenden; die App besitzt weitreichende Host-Rechte. Die Oberfläche läuft über Home Assistant Ingress. Die eigentlichen Dienste erreichst du über ihre Compose-Ports.

„Images laden“ lädt Images der eingetragenen Tags, „Start / Anwenden“ übernimmt die Konfiguration. „Container entfernen“ behält persistente Daten. „Logs“ zeigt die letzten 200 Zeilen pro Dienst nach dem Abruf. Bei Problemen zuerst das App-Protokoll prüfen.

Version 0.2 ist experimentell. Installation, Datensicherung, Wiederherstellung und Grenzen: [README](https://github.com/xwumps/ha-docker#readme).
