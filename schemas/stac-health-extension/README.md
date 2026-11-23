# STAC Health Extension

- **Title:** STAC Health Extension
- **Identifier:** <https://github.io>
- **Field Name Prefix:** `health`
- **Scope** Item, Collection
- **Extension Maturity Clasification** Proposal

## Beschreibung

Die **STAC Health Extension** erweitert STAC Collections und STAC Items um Metadaten für Gesundheits- und Umweltdaten. Die Codelisten entsprechen **ISO-19115** (`MD_ProgressCode`, `MD_MaintenanceFrequencyCode`,`MD_SpatialRepresentationTypeCode`), sodass eine verlustfreie Abbildung auf ISO 19115 und DCAT möglich ist. 

## Felder

| Feld | Typ | Pflicht | Zulässige Werte / Regeln | Beschreibung |
| :--- | :--- | :--- | :--- | :--- |
| `health:status` | string | Ja (Collection) | `completed`, `onGoing`, `planned`, `underDevelopment`, `historicalArchive`, `obsolete` | Bearbeitungsstand |
| `health:update_frequency` | string | Ja (Collection) | `continual`, `daily`, `weekly`, `fortnightly`, `monthly`, `quarterly`, `biannually`, `annually`, `asNeeded`, `irregular`, `notPlanned`, `unknown` | Rhythmus der Aktualisierung |
| `health:representation_type` | \[string\] | Ja (Collection) | 1–2 eindeutige Einträge: Genau ein räumlicher Code (`vector`, `grid`, `textTable`, `tin`, `stereoModel`, `video`), optional mit `timeSeries` | Räumliche Struktur, ggf. Zeitreihe |
| `health:spatial_resolution` | number | Bedingt (`grid`) | `> 0` (Meter). Pflicht, wenn `grid` enthalten ist. | Rasterweite / Punktabstand |
| `health:temporal_resolution` | string | Bedingt (`timeSeries`) | ISO-8601-Dauer (z. B. `P1D`, `P7D`). Pflicht bei `timeSeries`. | Abstand zwischen Zeitschritten |
| `health:scale` | integer | Empfohlen (`vector`) | `>= 1` | Bezugsmaßstabszahl (Nenner) |
| `health:format` | \[string\] | Empfohlen | `COG`, `GeoTIFF`, `NetCDF`, `Zarr`, `GeoJSON`, `FlatGeobuf`, `GeoParquet`, `GeoPackage`, `Shapefile`, `CSV`, `XLSX`, `Database`, `API` | Lesbare Formatangabe |
