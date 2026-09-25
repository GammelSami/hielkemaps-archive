# Repository instructions

## Language and identity

- Keep README.md and this file in English.
- Present this project as an independent, community-maintained archive.
- Never describe the archive as official or imply affiliation with, approval
  from, or endorsement by Hielke. Use “Maps by Hielke” and “Maps by community
  creators” to distinguish authorship without implying project status.

- Render map thumbnails as small inline images (180 px wide), rather than only
  showing their file paths.
- Make each map heading a hyperlink to its map information page, not the ZIP.
  Link community maps to the community overview and resource packs to their
  parent map page. Keep ZIP downloads in the version table. Do not add
  separate current-download or release-link lines above the thumbnail/table.
- Keep map sections in the order shown on the corresponding website listing,
  not alphabetical order. Append sitemap-only or archived-only maps after listed
  maps, keeping accompanying resource packs directly after their parent map.

## Archive completeness

- During updates, inspect the live website structure and check for changes before
  trusting the scraper. Capture every map discoverable from the website, sitemap,
  known URLs, and archive backups; do not assume the current listing is complete.
- Cross-check map listings, sitemap.xml, individual map pages, and known archived
  URLs. A listing-only count is not proof of completeness.
- Search backups fully, including archives nested inside other archives.
- Follow actual download links; do not rely only on title-cased slug guesses.
- Include publicly linked Java maps and accompanying resource packs. Identify
  Marketplace-only Bedrock products separately rather than counting them as saved.
- Preserve every existing distinct ZIP snapshot, including multiple snapshots
  with the same Minecraft version. Publish ZIPs as GitHub release assets.
- Verify live download contents against local snapshots and release assets using
  hashes. Verify ZIP integrity and generated download links before reporting success.
- Report the scope of completeness precisely. Do not claim all historical versions
  were found when Wayback/CDX could not be queried successfully.

## Archive.org

- Submit currently available map downloads and accompanying resource packs to
  Archive.org during an archive refresh, including byte-identical local downloads.
- Local deduplication must not suppress Save Page Now requests.
- Treat submission, completed capture, and verified matching ZIP content as distinct
  states. A successful local download or GitHub upload is not a Wayback success.
- Keep genuine snapshot URLs and timestamps; never manufacture Archive.org links
  from local download times. Record authentication, rate-limit and service failures
  explicitly, and retain incomplete work for retry.
- Keep credentials outside the repository and never print them in logs.

## Verified discovery pitfalls

- The 2026-09-20 sitemap includes /maps/arrow-fight, absent from /maps/.
  Its detail page links both the map and a separate resource pack.
- Map cards currently use onclick navigation; detail pages contain actual ZIP links.
- Thumbnail URLs may contain /media//maps/: normalize paths inside thumbnails/.
- Add focused regression tests for confirmed scraper and archiving failures.
