# Historical downloads found in external archives

Research date: 2026-09-20. Baseline: 87 archived ZIP snapshots.

Found and downloaded **nine additional world ZIPs and one accompanying resource-pack ZIP**. None matches an existing ZIP by either full-file SHA-256 or normalized uncompressed contents. All ten pass ZIP CRC checks. The separate resource pack is byte-identical to the `resources.zip` embedded in the recovered Spiral 2 world; it is not an additional map version.

These are third-party copies. Integrity and absence from our archive are verified; exact original release identity, absence of third-party edits, and in-game compatibility are not established. The versions below come from `level.dat` and identify the version that saved the world, not a gameplay compatibility test.

The downloads are saved locally under `archive_zips/_external_research/`. They have **not** been imported into the main version tables or published as GitHub release assets, and no new Wayback captures are claimed. The retrieval date is not a historical release or capture date.

| Map / artifact | World save version | Source |
| --- | --- | --- |
| Parkour Spiral | 1.12.2 | [Source page](https://mapcraft.me/parkour-maps/parkour-spiral) |
| Parkour Spiral 2 | 1.12.2 | [Source page](https://mapcraft.me/parkour-maps/parkour-spiral-2) |
| Parkour Paradise | 1.12.2 | [Source page](https://mapcraft.me/parkour-maps/parkour-paradise) |
| Parkour Paradise 2 | 1.9.4 | [Source page](https://mapcraft.me/parkour-maps/parkour-paradise-2) |
| Parkour Paradise 3 | 1.12.2 | [Source page](https://mapcraft.me/parkour-maps/parkour-paradise-3) |
| Parkour Paradise Sky Islands | 1.9.2 | [Source page](https://mapcraft.me/parkour-maps/parkour-paradise-sky-islands) |
| Parkour Pyramid | 1.17.1 | [Source page](https://www.mc-mod.net/parkour-pyramid-map/) |
| Parkour Spiral 2 Resource Pack | Resource pack | [Source page](https://www.minecraft-france.fr/map-parkour-spiral-2/) |
| Parkour Spiral | 1.17.1 | [Source page](https://archive.org/details/parkour-spiral-map-1.12.2) |
| Parkour Paradise | Unknown; uploader labels it 1.8 | [Source page](https://archive.org/details/parkour-paradise-map) |

## Findings that need careful labeling

- The Internet Archive item named “Parkour Spiral Map 1.12.2” actually contains a world saved by **1.17.1**. Its name must not be used as the version.
- The Pyramid article advertises **1.13.2**, but its current MediaFire ZIP contains a **1.17.1** world.
- The MapCraft Paradise 3 page advertises **1.11.2**, but its ZIP contains a **1.12.2** world.
- The Internet Archive Paradise file has neither `Data.Version` nor `DataVersion`. Its claimed **1.8** version therefore remains source-reported. Its `LastPlayed` value is consistent with 2015, but that editable field does not prove a release date.
- **Parkour Paradise: Sky Islands** is listed by MapCraft as a separate Hielke map, published in 2016, and was absent from our archive. Do not silently merge it into Paradise 3.

## Search limits and unsuccessful sources

Checked MapCraft downloads, Internet Archive catalog items, Minecraft-France, MineThatCraft, Mc-Mod, Minecraft Inside, and ru-minecraft leads. This is a targeted search, not a claim that every historical release has been found.

- Minecraft Inside and ru-minecraft downloads/pages returned HTTP 403 during direct retrieval.
- The old Mc-Mod Paradise download redirected to a response that was not a ZIP. It was not counted as a recovered version.
- No gameplay runs or authoritative original-release checksum comparison were performed.

## Reproducible evidence

[Machine-readable findings](external-archive-findings.json) records source URLs, local paths, full SHA-256 hashes, file sizes, world versions, and comparison results. The baseline content-hash inventory is retained locally at `archive_zips/_external_research/inventory.json`.
