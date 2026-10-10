export type ApprovedPhilatelicAsset = {
  id: "japan-atlas-01";
  countryCode: "JP";
  src: string;
  width: number;
  height: number;
  alt: string;
};

export const JAPAN_ATLAS_STAMP = {
  id: "japan-atlas-01",
  countryCode: "JP",
  src: "/img/japan/philatelic/japan-atlas-stamp-01.webp",
  width: 520,
  height: 693,
  alt: "Fictional Atlas Japan travel stamp",
} as const satisfies ApprovedPhilatelicAsset;
