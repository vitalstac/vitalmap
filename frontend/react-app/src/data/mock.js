export const BBOX = "5.87,50.32,9.46,52.53";

export const exampleQuestions = [
  "Hausärzte in Münster?",
];

export const initialMessages = [
  { id: 1, role: "user", text: "beispiel frage1" },
];

export const results = [
  { id: "pm25", title: "PM2.5 – Jahresmittel", provider: "EEA", period: "2020–2023", badges: ["Raster", "abgeschlossen", "jährlich"] },
  { id: "heat", title: "Heiße Tage pro Jahr", provider: "DWD", period: "1951–2024", badges: ["Raster", "laufend"] },
  { id: "pop", title: "Bevölkerung 100 m", provider: "WorldPop", period: "2020", badges: ["Raster", "abgeschlossen"] },
];

export const details = {
  pm25: {
    title: "PM2.5 – Jahresmittel (interpoliert), Europa",
    description:
      "Interpolierte Jahresmittel der PM2.5-Konzentration auf Basis von Messstationen, Modell- und Hilfsdaten. Rasterweite 1 km, Europa. Anbieter: European Environment Agency.",
    categories: "ISO 19115 environment, health · INSPIRE hh · Health: environmental-exposure",
    license: "CC BY 4.0",
    keyData: [
      ["Räumliche Auflösung", "1 km (health:spatial_resolution = 1000)", true],
      ["Zeitliche Auflösung", "jährlich (P1Y)", true],
      ["Zeitraum", "2020-01-01 – 2023-12-31", true],
      ["Einheit", "µg/m³ (unit = ug/m3)", false],
      ["Koordinatenreferenzsystem", "EPSG:3035 (ETRS89 / LAEA Europe)", true],
      ["Repräsentationstyp", "Raster (grid)", true],
      ["Status · Aktualisierung", "abgeschlossen (completed) · jährlich (annually)", true],
      ["Format · Datentyp", "COG · image/tiff; profile=cloud-optimized · float32", false],
      ["Metadatensprache · Datensprache", "Englisch (en) · Englisch (en)", false],
    ],
    lineage: ["Messstationsdaten", "Modell- und Hilfsdaten", "Interpolation auf 1-km-Raster"],
    contact: [{ name: "European Environment Agency", role: "Anbieter" }],
    links: [
      { label: "Originaldaten (COG)", href: "#" },
      { label: "Publikation", href: "#" },
    ],
  },
};
