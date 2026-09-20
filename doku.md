# Hielke Maps Archiv-Doku

Das Skript sammelt offizielle und Community-Maps von hielkemaps.com,
liest Minecraft-Versionen aus `level.dat`, sichert ZIPs und Thumbnails und
erzeugt getrennte Markdown-Tabellen. Bereits bekannte Download-URLs bleiben
auch dann enthalten, wenn sie von den Übersichtsseiten verschwinden.

## Einrichtung und Aktualisierung

Voraussetzungen: Python 3.10+, Git und die angemeldete GitHub CLI `gh` mit
Schreibzugriff auf das Zielrepository. Das Repository muss bereits existieren
und einen Branch `main` enthalten.

Im Projektverzeichnis:

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt
gh auth login
.venv/bin/python -u build_hielke_archive_md.py
```

Standardziel: `GammelSami/hielkemaps-archive`. Ein anderes Repository lässt
sich über `ARCHIVE_REPO=owner/repo` festlegen.

Bei einem Wayback-Ausfall:

```sh
.venv/bin/python -u build_hielke_archive_md.py --skip-wayback
```

`--skip-upload` aktualisiert nur lokal. Die erzeugten GitHub-Links funktionieren
erst, nachdem die zugehörigen Release-Anhänge hochgeladen wurden.

## Dateien und Speicherung

- `hielke-maps-archive-hielke.md` und `hielke-maps-archive-community.md`:
  neuester Snapshot je erkannter Minecraft-Version, Download- und Wayback-Links.
- `archive_zips/<Map>/YYYYMMDDHHMMSS__<Minecraft-Version>.zip`:
  lokaler ZIP-Bestand; wird nicht in Git gespeichert.
- `archive_zips/_no_wayback.json`: merkt sich lokale Snapshots ohne bestätigten
  Wayback-Zeitstempel. Zusammen mit dem ZIP-Bestand sichern.
- `thumbnails/`: Bilder und `INDEX.md`, in Git gespeichert.

Je Map wird ein GitHub-Release `map-<name>` erstellt. Alle lokalen ZIPs dieser
Map werden als Anhänge hochgeladen, auch mehrere Snapshots derselben
Minecraft-Version. Vorhandene Anhänge werden übersprungen und nicht ersetzt.
Byte-identische Downloads werden pro Map anhand ihres SHA1 dedupliziert.
Der SHA1 in den Tabellen ist auf zwölf Zeichen gekürzt und dient als
Inhaltskennung. Der Zeitstempel bezeichnet den Snapshot-/Sicherungszeitpunkt
in UTC, nicht das Veröffentlichungsdatum der Map.

Ein Git-Clone enthält die Tabellen, das Skript und die Thumbnails. ZIPs müssen
separat aus den Releases heruntergeladen werden. Der lokale ZIP-Bestand sollte
für inkrementelle Aktualisierungen erhalten bleiben.

Download- und Wayback-Fehler erscheinen am Ende der jeweiligen Tabelle.
Fehlgeschlagene Release-Uploads brechen den Lauf vor dem Schreiben der Tabellen
ab; nach Behebung kann der Lauf wiederholt werden. Das Skript führt keinen
Git-Commit oder Push aus.

## Tests

```sh
.venv/bin/python -m unittest -v test_archive
```

Die Tests prüfen ZIP-Validierung und Deduplizierung, den Erhalt mehrerer
Snapshots derselben Version beim Upload, Release-Abfragefehler und
Thumbnail-Pfade mit doppeltem Schrägstrich.

## Discovery and Archive.org verification

The updater checks the map listing, community listing, sitemap, and every map
page linked by the sitemap/listing. It reads actual ZIP links, including
accompanying resource packs. Arrow Fight is a known sitemap-only map.

Save Page Now is requested for every current download, even if its ZIP already
exists locally. The updater submits a job, polls its status, downloads the
resulting capture, and checks SHA256 against the live ZIP before linking it.
`wayback-status.json` records each current URL's outcome and any job ID/error.
`archive_zips/_wayback_verified.json` preserves verified capture bindings without
renaming local files or release assets. Keep this file with the ZIP backup.

Save Page Now currently requires authentication. Keep an Internet Archive config
outside this repository at `~/.config/ia.ini` (or pass its path via `IA_CONFIG`):

```ini
[s3]
access = YOUR_ACCESS_KEY
secret = YOUR_SECRET_KEY
```

Obtain your own keys at https://archive.org/account/s3.php and restrict the file
with `chmod 600 ~/.config/ia.ini`. Never commit this file or print its values.

`--skip-history` skips historical CDX discovery while still requesting fresh
Wayback captures for all current ZIPs. `--skip-wayback` skips both operations and
must not be reported as a successful Archive.org refresh. Download, save or CDX
errors produce a nonzero exit status after saving available results.

Retry only incomplete saves after resolving an outage or login problem:

```sh
.venv/bin/python -u retry_wayback.py
```

This retains successful captures, resumes known jobs, retries failed jobs, checks
ZIP content, persists progress, and refreshes the tables. If Archive.org refuses
another save because today's resource limit is reached, today's existing capture
is fetched and hash-verified instead. It does not bypass that limit.
