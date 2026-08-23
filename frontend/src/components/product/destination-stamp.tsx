import Image from "next/image";
import type { ApprovedPhilatelicAsset } from "@/lib/design/philatelic-assets";

export type DestinationStampProps = {
  asset: ApprovedPhilatelicAsset;
  size: "thumbnail" | "feature";
  decorative?: boolean;
  routeLabel?: string;
  dateLabel?: string;
  issued?: boolean;
};

const SIZE_CLASS = {
  thumbnail: "w-[118px] sm:w-[132px]",
  feature: "w-[min(58vw,260px)]",
} as const;

export function DestinationStamp({
  asset,
  size,
  decorative = false,
  routeLabel,
  dateLabel,
  issued = false,
}: DestinationStampProps) {
  const hasOverlay = !decorative && (routeLabel || dateLabel);

  return (
    <figure
      className={`relative isolate inline-block ${SIZE_CLASS[size]} text-text ${issued ? "motion-safe:duration-base" : ""}`}
      data-destination-stamp={asset.id}
    >
      <div className="relative border-2 border-border bg-surface p-2 shadow-1">
        <Image
          src={asset.src}
          width={asset.width}
          height={asset.height}
          alt={decorative ? "" : asset.alt}
          aria-hidden={decorative ? "true" : undefined}
          priority={false}
          sizes={size === "feature" ? "(max-width: 768px) 58vw, 260px" : "170px"}
          className="block h-auto w-full"
        />

        {hasOverlay ? (
          <figcaption className="absolute left-[18%] right-[22%] bottom-[12%] border border-border bg-surface/95 px-2 py-1 text-center shadow-1">
            {routeLabel ? (
              <span className="block font-mono text-[11px] font-medium leading-tight tracking-[0.08em] text-text">
                {routeLabel}
              </span>
            ) : null}
            {dateLabel ? (
              <span className="block font-mono text-[9px] leading-tight tracking-[0.06em] text-text-muted">
                {dateLabel}
              </span>
            ) : null}
          </figcaption>
        ) : null}

        <div
          aria-hidden="true"
          data-testid="destination-stamp-postmark"
          className="absolute -right-2 bottom-5 aspect-square w-[24%] min-w-10 rounded-full border border-border bg-transparent opacity-35"
        />
      </div>
    </figure>
  );
}
