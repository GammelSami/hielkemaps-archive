# Hielke Maps Archiv-Doku

## Ziel
Aus den Seiten
- `https://hielkemaps.com/maps/`
- `https://hielkemaps.com/community-maps/`

wurde ein lokales Archiv gebaut mit:
- Wayback-Links pro Map-Version
- lokal gespeicherten ZIP-Snapshots
- separater Community-/Official-Aufteilung
- lokal gespeicherten Map-Thumbnails

## Wichtige Dateien
- `build_hielke_archive_md.py`
  - Hauptskript zum Einsammeln von Maps, Wayback-Snapshots und Versionen aus `level.dat` (NBT via `nbt2yaml`).
- `hielke-maps-archive-official.md`
  - Offizielle Maps.
- `hielke-maps-archive-community.md`
  - Community-Maps.
- `archive_zips/`
  - Lokale ZIP-Snapshots je Map.
- `thumbnails/`
  - Gespeicherte Thumbnail-Bilder + `thumbnails/INDEX.md`.

## Aktueller Stand
- Official Maps: alle mit `1.21.11`-Zeile inkl. Archive.org-Link.
- Community Maps: enthalten den jeweils aktuell erkannten Stand (nicht zwingend `1.21.11`).
- Live-Download-Spalte wurde entfernt (gewünscht).

## ZIP-Namensschema
Dateiname:
- `YYYYMMDDHHMMSS__<version>.zip`

Beispiel:
- `20260211182405__1.20.2.zip`

`YYYYMMDDHHMMSS` ist der Snapshot-/Save-Zeitpunkt (UTC), nicht zwingend ein eindeutiger Inhalt.

## Duplikate / Dedupe
Es gab doppelte Dateien mit unterschiedlichen Timestamps, aber identischem Inhalt (gleicher SHA1).

Gefixt:
- bestehende Duplikate wurden bereinigt.
- im Skript wurde Dedupe eingebaut:
  - identischer ZIP-Inhalt pro Map-Ordner wird nicht erneut gespeichert.

## URL-Normalisierung
Community-Downloadlinks mit Leerzeichen wurden auf URL-encoded Form gebracht (`%20`), damit
- Live-Download funktioniert,
- Wayback-`/save` nicht an ungültigen URLs scheitert.

## Script-Verhalten (`build_hielke_archive_md.py`)
- liest Map-Quellen (`maps` + `community-maps`)
- bildet Official-Downloadlinks aus Slugs (`/maps/<slug>` -> `/downloads/<Title Case>.zip`)
- holt CDX-Snapshots von Wayback
- lädt ZIPs und liest Minecraft-Version aus `level.dat`
- schreibt Markdown-Tabellen
- speichert ZIPs lokal in `archive_zips/<Map>/...`
- mit Retry/Backoff + leichtem Request-Delay
- inkrementell: vorhandene lokale ZIPs werden wiederverwendet

## Thumbnails
Gespeichert unter:
- `thumbnails/maps/...`
- `thumbnails/community-maps/...`

Index:
- `thumbnails/INDEX.md`

## Hinweis zur Regeneration
Falls neu generiert wird:
- `build_hielke_archive_md.py` erzeugt standardmäßig `hielke-maps-archive.md`.
- Aktuell nutzt das Projekt getrennte Dateien:
  - `hielke-maps-archive-official.md`
  - `hielke-maps-archive-community.md`

Bei Bedarf nach Lauf erneut splitten oder den Split direkt ins Skript integrieren.
