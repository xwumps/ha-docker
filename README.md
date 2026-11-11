# ha-docker · Docker Studio für Home Assistant OS

Eine Home-Assistant-App (früher Add-on) für **Docker und Docker Compose V2** auf deinem HA-OS-Gerät. Native Container, `docker run`-Import, Dockerfile-Builds, Compose-Projekte, Jotion-Einrichtung, Status und Logs. Normale lokale Docker-Volumes werden im persistenten App-Datenordner gespeichert und beim Home-Assistant-Backup dieser App mitgesichert.

**Version 0.3.0 ist experimentell.** Unterstützt werden `amd64` und `aarch64`. Der Container wird auf dem Gerät gebaut. Ein direkter Installationstest mit dem Home-Assistant-Supervisor steht noch aus; Details im [Prüfbericht](TESTREPORT.md).

## Installation und Update

1. **Einstellungen → Apps → App-Store → ⋮ → Repositories** öffnen. In älteren HA-Versionen heißen die Punkte „Add-ons“ und „Add-on-Store“.
2. `https://github.com/xwumps/ha-docker` hinzufügen.
3. **Docker Studio → Installieren**. Das erste Bauen benötigt Internet und kann einige Minuten dauern.
4. **Schutzmodus dieser App ausschalten**, dann **Starten → Weboberfläche öffnen**.
5. Optional „Beim Booten starten“ und „In der Seitenleiste anzeigen“ aktivieren.

Für ein Update im Store „Nach Updates suchen“ und bei der App „Aktualisieren“ wählen. Version 0.2.0 ist als Änderung mit manueller Bestätigung markiert: **Ein App-Stopp stoppt jetzt auch die laufenden Projekte. Beim nächsten App-Start werden sie fortgesetzt.** Während HA-Backups werden die Projekte ebenfalls angehalten.

Eine lokale ZIP-Installation ist weiterhin möglich: Den Ordner `compose_studio` nach `/addons/compose_studio` auf HA OS kopieren und im Store die lokalen Apps neu einlesen. Eine ZIP-Download-URL gehört nicht in den Repository-Dialog.

## Normale Docker-Container verwenden

**Docker-Container → Neu** öffnet den nativen Docker-Bereich. Hier ist keine Compose-Datei erforderlich. Die App verwendet `docker container create/start/stop`, `docker image` und `docker build`; native Container werden nicht in Compose-Projekte umgewandelt.

### Per Formular

1. Einen Namen und ein Image wie `nginx:alpine` eintragen.
2. Ports (z. B. `8090:80`), Umgebungsvariablen (`NAME=WERT`) und persistente Mounts nach Bedarf eintragen, jeweils eine Zuordnung pro Zeile.
3. **Container speichern → Start / Anwenden**. Ein fehlendes Image wird standardmäßig geladen.
4. **Status**, **Logs**, **Stoppen**, **Neustarten** oder **Container entfernen** verwenden. Entfernen behält die gespeicherte Definition und persistenten Daten.

Die tatsächlichen Docker-Containernamen beginnen mit `hd_`. Verwaltet werden die in dieser App angelegten nativen Container; Namen und interne Labels werden vor Änderungen geprüft. Der bestehende App-Slug/Installationsordner bleibt `compose_studio`: Ein Update der bisherigen App genügt, eine Neuinstallation ist nicht erforderlich. Native Profilnamen beginnen mit a–z und bestehen aus maximal 40 Zeichen aus a–z, 0–9, `_` und `-`.

### Einen docker run-Befehl übernehmen

Im nativen Bereich **docker run-Befehl übernehmen** öffnen und z. B. einfügen:

```sh
docker run -d --init --name web -p 8090:80 -e TZ=Europe/Berlin nginx:alpine
```

**In Formular übernehmen** liest die Optionen ein. Einstellungen prüfen, speichern und **Start / Anwenden** wählen. Mehrzeilige Befehle mit Backslash-Zeilenfortsetzung und zitierte Argumente werden unterstützt. `docker container run` ist ebenfalls zulässig. Die Formulare zeigen die übernommenen Optionen zur Kontrolle an.

Unterstützt werden Name, Ports, explizite Umgebungsvariablen, Volumes/Bind-Mounts, einfache `--mount`-Angaben, Neustartregel, vorhandenes Netzwerk, Entrypoint, Benutzer, Arbeitsverzeichnis, Hostname, Speicher-/CPU-Limit, Capabilities, Geräte, zusätzliche Hosts, DNS, tmpfs, Labels, `--init`, `--read-only`, `--privileged` und die Image-Laderegel. Nicht unterstützte Optionen erzeugen eine Fehlermeldung und werden nicht stillschweigend ignoriert.

Das ist kein Host-Terminal: `sudo`, `--context`, Shell-Verkettungen, Host-Variablenauflösung, interaktives `-it`, `--rm` und `--env-file` gehören nicht zu diesem Import. Werte aus einer `.env` im Variablenfeld eintragen. Für einen Shell-Befehl im **eigenen Container** kann nach dem Start unter **docker exec** etwa `sh -c 'ls /data; echo fertig'` ausgeführt werden. Die Ausgabe wird nach Abschluss angezeigt; es gibt keine interaktive Terminalsitzung.

### Dockerfile-Projekte bauen

Unter **Dockerfile-Projekt importieren** ein ZIP/TAR/TAR.GZ mit `Dockerfile` und Quell-/Kontextdateien hochladen. Den Dockerfile-Pfad im Importformular angeben: Standard `Dockerfile`, alternativ z. B. `docker/Dockerfile`. Das Projekt darf in einem gemeinsamen Archiv-Oberordner liegen. Beispiel:

```dockerfile
FROM busybox:1.37.0
COPY index.html /www/index.html
EXPOSE 80
CMD ["httpd", "-f", "-p", "80", "-h", "/www"]
```

`index.html` ebenfalls ins Archiv legen. Nach dem Import z. B. Port `8090:80` setzen und speichern. **Start / Anwenden** baut ein fehlendes Image und startet den Container. Für Quellcode-Änderungen **Image bauen → Start / Anwenden** verwenden; ein bereits vorhandenes Image wird beim Start nicht automatisch neu gebaut.

Der Kontext kann auch nach dem Speichern über **Dateien im Container-/Build-Kontext** ergänzt werden. Dockerfile-Pfad, Build-Target und explizite Build-Argumente lassen sich im Build-Bereich einstellen. `.dockerignore` wird von Docker berücksichtigt. Reguläre Dateirechte aus ZIP/TAR bleiben erhalten, einschließlich ausführbarer Skripte; Setuid-/Setgid-Bits werden entfernt. Bei Einzeldatei-Uploads bleiben vorhandene Rechte erhalten; neue Dateien sind normalerweise lesbar (0644). Mit „Datei ausführbar machen“ lassen sich z. B. neue Entrypoint-Skripte mit 0755 hochladen. Archiv- und Upload-Grenzen entsprechen dem allgemeinen Projektimport (12 MiB Archiv, 32 MiB entpackt; einzelne Datei-Uploads bis 2 MiB).

Ein Build führt die Anweisungen des hochgeladenen Dockerfiles in Docker aus. Vertrauenswürdige Projekte und passende Basisimages für die Gerätearchitektur verwenden. Eigene Images erhalten den Tag `ha-docker/<name>:local`. Das optionale Image-Target betrifft mehrstufige Dockerfiles; es ist kein anderer Docker-Host.

### Persistente Daten nativer Container

- `datenname:/data` legt verwalteten lokalen Speicher unter `/data/storage/docker-volumes/` an. Gleiche logische Namen teilen Daten zwischen nativen Containern dieser App. Die tatsächlichen Docker-Volumenamen sind intern mit `hdv_` versehen; bestehende fremde Volumes gleichen Namens werden nicht automatisch übernommen.
- `./config.json:/app/config.json:ro` bezieht sich auf `context/config.json` im eigenen Container-Projekt. Dateien vorher über den Upload bereitstellen. Fehlende relative Bind-Pfade werden als Ordner angelegt.
- Durch `VOLUME` im Image vorgegebene, noch nicht zugeordnete Pfade werden automatisch mit persistentem App-Speicher verbunden. Damit bleiben diese Daten bei Container-Neuanlage und HA-Backups erhalten.
- Andere absolute Host-Datenpfade sind nicht automatisch sicherbar und werden abgewiesen. Als explizite Host-Ressource kann der Docker-Socket eingebunden werden; ebenso sind `/dev/`-Geräte möglich. Socket/Geräte/Host-Kernel sind keine im Backup gespeicherten Nutzdaten.

Die beschreibbare Container-Schicht, tmpfs und andere flüchtige Zustände werden nicht als Nutzdaten gesichert. Wichtige Anwendungsdaten auf einen persistenten Mount legen.

## Jotion ohne Terminal installieren

1. In Docker Studio **Installieren / Importieren → Jotion einrichten** öffnen.
2. Projektname, einen freien HTTP-Port (z. B. 8090) und die **vom Browser erreichbare Adresse** eingeben, z. B. `http://192.168.1.20:8090`. Hier die IP des HA-Laptops einsetzen; `localhost` würde auf dem anderen Gerät auf dieses andere Gerät zeigen.
3. Die Version leer lassen für das neueste stabile Release oder z. B. `1.0.1` eintragen.
4. **Jotion vorbereiten** lädt das offizielle Release-Paket mit Compose-Datei, Caddyfile und Zusatzdateien. Es erzeugt eindeutige Datenbank-/Redis-Passwörter, Master Key und Auth-Secret und trägt die fertigen Images aus `ghcr.io/xwumps/jotion` mit der gewählten Version ein.
5. **Start / Anwenden** lädt die benötigten Images und startet die Dienste einschließlich Datenbankmigrationen. Mit **Status** und **Logs** prüfen; danach Jotion unter der angegebenen Adresse öffnen.

Du musst keinen `curl | bash`-Befehl ausführen. Mitgelieferte Installations-/Update-Skripte werden nicht ausgeführt. Das Jotion-Paket wird, wenn GitHub einen Digest liefert, gegen dessen SHA256-Prüfsumme geprüft. Der Assistent richtet zunächst HTTP im LAN ein; eine eigene HTTPS-/Domain-Konfiguration ist separat möglich. Für HTTPS die Compose-Ports und Caddy-Konfiguration passend ergänzen.

Den `JOTION_MASTER_KEY` aus `.env` zusätzlich im Passwortmanager sichern. Er ist auch im HA-App-Backup enthalten; ein getrenntes Exemplar hilft, wenn dieses Backup nicht verfügbar ist.

Jotion-Version aktualisieren: `JOTION_VERSION` in `.env` auf eine verfügbare Version setzen, speichern, **Images laden**, **Start / Anwenden**. Wenn das neue Release geänderte Zusatzdateien benötigt, diese ebenfalls aktualisieren. Der aktuelle Assistent importiert neue Projekte und überschreibt bestehende Projekte nicht. Die unveränderten upstream Shellskripte nicht für ein von Docker Studio verwaltetes Projekt verwenden: Docker Studio nutzt den Projektnamen `cs_<name>` und eine eigene Laufzeitdatei.

## Andere Compose-Apps importieren

Unter **Installieren / Importieren → Compose-Projekt importieren** ein ZIP-, TAR- oder TAR.GZ-Paket und einen neuen Projektnamen wählen. Im Hauptverzeichnis, optional unter einem gemeinsamen Oberordner, muss genau eine der Dateien `compose.yaml`, `compose.yml`, `docker-compose.yaml`, `docker-compose.yml` liegen. Sie wird intern als `compose.yaml` gespeichert.

Zusatzdateien und eine vorhandene `.env` bleiben erhalten. Fehlt `.env`, wird `.env.example` übernommen oder eine leere `.env` angelegt. Die Platzhalter dann im Editor ausfüllen. Anders als der spezielle Jotion-Assistent erzeugt ein allgemeiner Import keine anwendungsspezifischen Schlüssel.

Archive: maximal 12 MiB komprimiert, 32 MiB entpackt und 1500 Einträge. Symlinks, Hardlinks, Spezialdateien, Pfadüberschreitungen, `.git`, `node_modules` und interne `.studio*`-Dateien werden abgewiesen. Es wird kein Code aus einem Archiv ausgeführt. Importierte Projekte überschreiben keine bestehenden Projekte.

Unter **Zusatzdateien im Projekt** lassen sich weitere Dateien bis 2 MiB speichern oder ersetzen, etwa mit dem Pfad `docker/Caddyfile`. Compose und `.env` werden im Haupteditor bearbeitet. Anschließend **Prüfen → Start / Anwenden**.

Im **Compose-Bereich** benötigt jeder Dienst ein fertiges `image:`. `build:` wird aus der Laufzeitkonfiguration entfernt; gestartet wird mit `--no-build`. Quellcode-Builds sind im nativen Dockerfile-Bereich verfügbar; der Compose-Bereich selbst führt weiterhin keine Builds aus. Fremde Anleitungen mit beliebigen Shell-Befehlen lassen sich deshalb nicht unverändert in die Oberfläche kopieren.

## Datenordner und HA-Backups

Die App hat ihr eigenes persistentes `/data`:

```text
/data/
├── stacks/<projekt>/       # Compose-YAML, .env und Zusatzdateien
├── containers/<name>/      # Native Definition, angewendete Konfiguration und Kontext
├── storage/                # Nutzdaten verwalteter lokaler Volumes
└── docker-images/          # TAR-Sicherungen selbst gebauter/lokaler Images
```

Die Oberfläche zeigt den tatsächlichen Host-Pfad an. Ein Docker-Volume erhält einen lokalen Bind-Treiber mit einem Datenverzeichnis unter `/data/storage`. Compose-Semantik, Dateirechte und der Datenbestand bleiben damit erhalten, während die Nutzdaten im App-Backup liegen. Relative Bind-Mounts wie `./daten:/data` liegen im Projektordner und sind ebenfalls enthalten.

**In Home Assistant ein Vollbackup oder ein Teilbackup mit ausgewähltem „Docker Studio“ anlegen.** Ein HA-Backup, das diese App ausschließt, enthält ihre Daten nicht.

Ablauf bei laufender App:

1. Der Supervisor führt `backup_pre` aus. Die App sperrt Änderungen und stoppt die laufenden Container ihrer bekannten Projekte mit bis zu 30 Sekunden Wartezeit.
2. Home Assistant sichert die App-Daten einschließlich YAML, `.env`, Zusatzdateien und Volume-Nutzdaten. Die Projekte bleiben während der Sicherung angehalten.
3. `backup_post` startet die zuvor aktiven Projekte wieder. Vorher gestoppte Projekte bleiben gestoppt.

Läuft gerade eine Installation/ein Compose-Vorgang, wird der Backup-Vorlauf mit einer Fehlermeldung abgebrochen. Den Vorgang beenden lassen und die Sicherung erneut starten. Bei Fehlern im Vorlauf versucht die App, zuvor aktive Projekte wieder zu starten. Bleibt der Neustart nach einem Fehler aus, das App-Protokoll prüfen und die App neu starten. Es wird nicht stillschweigend ein als vollständig ausgegebener Schnappschuss externer Daten angelegt.

Beim normalen App-Stopp werden die Projekte geordnet angehalten und der Wiederanlauf gespeichert. So sind ihre Daten auch in einem Backup einer ordentlich gestoppten App in Ruhe. Nach einem erzwungenen Abbruch/Crash erst die App wieder starten und ihren Zustand prüfen. Änderungen über andere Docker-Werkzeuge während eines Backups werden nicht koordiniert.

### Wiederherstellung

Das HA-Backup mit dieser App wiederherstellen und Docker Studio starten. Die App bildet die Pfade auf den aktuellen Host-Datenordner ab und setzt die zum Zeitpunkt des Backups aktiven Projekte fort. Auch wenn der Datenpfad auf dem Zielgerät anders ist, werden neue Volume-Hüllen auf die wiederhergestellten Daten eingerichtet.

Bei nativen Containern werden **selbst gebaute und andere nur lokal verfügbare Images als TAR im App-Datenordner mitgesichert** und bei Bedarf vor dem Wiederanlauf geladen. Das kann Backups deutlich vergrößern; mehrere gebaute Versionen können zusätzlichen Speicher belegen. Registry-Images werden nicht pauschal archiviert: Beim Wiederanlauf müssen sie vorhanden oder über ihren gespeicherten Registry-Digest abrufbar sein. Für Compose-Images gilt weiterhin: lokal vorhanden oder aus der Registry abrufbar. Das Zielgerät muss zur Architektur der verwendeten Images passen. Eigene Image-Registries müssen weiterhin erreichbar und gegebenenfalls eingerichtet sein. Bei nativen Containern setzt ein Backup-/App-Wiederanlauf die zuletzt angewendete Konfiguration und Image-ID fort; gespeicherte, noch nicht angewendete Änderungen bleiben als Entwurf erhalten. **Start / Anwenden** übernimmt dagegen ausdrücklich die aktuelle Definition und ein gegebenenfalls neu gebautes/geladenes Image.

### Unterstützter Speicher

Automatisch erfasst werden verwaltete native Volumes, normale lokale benannte Compose-Volumes und Bind-Dateien/-Ordner **innerhalb des App-Datenordners**. Externe Volumes, eigene Volume-Treiber/`driver_opts`, Bind-Pfade außerhalb des App-Datenordners, `volumes_from` sowie explizite anonyme Compose-Volumes werden nicht als vollständig sicherbar akzeptiert. Im Compose-Bereich bei einem Image mit implizitem `VOLUME` dieses Containerziel explizit mit einem benannten Volume belegen; im nativen Docker-Bereich werden Image-Volumes automatisch persistent zugeordnet. Ein Compose-Projekt mit einem nach dem Start erkannten anonymen Volume wird wieder gestoppt und meldet den nötigen YAML-Eintrag.

Geräte, Remote-Datenbanken, externe Cloud-Dienste und andere außerhalb der App liegende Ressourcen werden durch dieses Backup nicht gespeichert. Für sie bleibt der jeweilige Sicherungsweg notwendig. Globale Docker-Netzwerke und die Home-Assistant-Installation werden nicht durch Docker Studio verändert oder gesichert.

### Upgrade von Version 0.1.0

Bereits vorhandene lokale Volume-Daten eines bekannten Projekts werden bei der Übernahme im angehaltenen Zustand in den App-Datenordner kopiert. Dateirechte und Eigentümer werden beim Kopieren erhalten. Die ursprünglichen Docker-Volumes werden **nicht gelöscht**. Der Datenbestand kann vorübergehend doppelt Speicher belegen. Nach einer geprüften Sicherung und Wiederherstellung lassen sich ungenutzte Originalvolumes gezielt manuell entfernen; die App bietet kein globales Pruning an.

Bei externen/ungewöhnlichen Volumes oder nicht unterstützten alten Mounts bricht die Übernahme mit einer erklärenden Meldung ab. Die Originaldaten bleiben erhalten. Vor dem Upgrade wichtige Bestandsdaten unabhängig sichern.

## Bedienung

- **Speichern**: YAML/.env ändern; noch keine Containeränderung.
- **Prüfen**: ursprüngliche Compose-Konfiguration validieren.
- **Start / Anwenden**: Speicher vorbereiten, bei bestehenden laufenden Projekten kurz stoppen und die gespeicherte Konfiguration mit fertigen Images anwenden.
- **Images laden**: neue Images für die eingetragenen Tags laden; anschließend **Start / Anwenden**.
- **Stoppen**: Projekt stoppen, Daten behalten.
- **Container entfernen**: `compose down` ohne `--volumes`. Container-Netzwerke werden entfernt; persistente Daten bleiben. Daten allein in der beschreibbaren Container-Schicht sind kein dauerhafter Speicher.
- **Status / Logs**: Zustand bzw. letzte 200 Logzeilen pro Dienst. Die Ausgabe erscheint nach Abschluss des Vorgangs, spätestens nach dessen Zeitlimit von zehn Minuten.

Ein Vorgang zur Zeit. Ein Neuladen der Oberfläche kann sich mit einem noch laufenden Vorgang verbinden. Ein App-Stopp unterbricht laufende Compose-Befehle und hält danach die Projekte an.

## Zugriff und Grenzen

Die Oberfläche läuft ausschließlich über Home Assistant Ingress; kein Verwaltungsport am Host. Nur die dokumentierte Supervisor-IP `172.30.32.2` wird akzeptiert. API-Aufrufe benötigen zusätzlich einen Sitzungstoken. Die Seitenleiste wird Administratoren angezeigt.

Docker-Socket-Zugriff ermöglicht weitreichende Kontrolle über den HA-Host. Der Projekt-Präfix `cs_` ist keine Sicherheitsgrenze gegenüber absichtlich privilegierten Compose-Dateien. Nur vertrauenswürdige Projekte importieren. Eigene Dienste teilen sich CPU, RAM, Speicherplatz und Host-Ports mit Home Assistant.

Remote-Docker-Endpunkte, Git-Synchronisierung, interaktive Terminals und automatische Release-Upgrades sind nicht enthalten. Ein vorbereitetes Projekt lässt sich vor dem ersten Start im Docker-Formular bzw. im Compose-YAML/.env prüfen und anpassen.

## Entwicklung

```sh
python3 -m unittest discover -s tests -v
docker build -t compose-studio:dev compose_studio
python3 tests/integration.py
```

Python-Standardbibliothek, Docker-CLI, Buildx und Compose V2.40.3 aus dem offiziellen `docker:28.5.2-cli`-Image. Kein zusätzlicher Docker-Daemon. Die Integration prüft auch Backup-Hooks und eine Wiederherstellung in einen anderen Host-Datenpfad. Sie startet und entfernt ausschließlich eigene Testressourcen.

## Referenzen

- [Home Assistant: App-Konfiguration und Backup-Hooks](https://contributors.home-assistant.io/apps/reference/configuration/)
- [Home Assistant: Ingress](https://contributors.home-assistant.io/apps/guides/ingress/)
- [Jotion: Installationsskript](https://github.com/xwumps/jotion/blob/main/scripts/install.sh)
- [Docker Compose](https://docs.docker.com/compose/)
