# VitalMap logo

| File | Use |
| --- | --- |
| `vitalmap-logo.svg` | Icon (map pin with pulse line), any size |
| `vitalmap-logo-512.png` | Icon as PNG, e.g. GitHub organisation avatar |
| `vitalmap-wordmark-light.svg` / `.png` | Icon and name for light backgrounds |
| `vitalmap-wordmark-dark.svg` / `.png` | Icon and name for dark backgrounds |
| `../../../frontend/react-app/public/favicon.svg` | Favicon of the web app |

The READMEs use the PNG wordmarks, because SVG text depends on the fonts installed on the viewer's machine.

## Colours

Taken from the web app's design tokens (`frontend/react-app/src/styles/tokens.css`).

| Name | Light | Dark |
| --- | --- | --- |
| Brand | `#0f766e` | `#2aa89a` |
| Text | `#16282b` | `#e5eeed` |
| Muted text | `#5b6d70` | `#9bb0b2` |

## Web app

Add the favicon to `frontend/react-app/index.html`:

```html
<link rel="icon" type="image/svg+xml" href="/favicon.svg" />
```

In the header, `vitalmap-logo.svg` can replace the placeholder symbol next to "VitalMap".
