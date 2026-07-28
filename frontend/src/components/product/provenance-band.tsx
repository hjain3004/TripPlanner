import { TrustChip } from "./trust-chip";

interface ProvenanceBandProps {
  sourceUrl?: string;
  lastVerified?: string;
  verifiedBy?: string;
  confidence?: number;
}

export function ProvenanceBand({
  sourceUrl,
  lastVerified,
  verifiedBy,
  confidence,
}: ProvenanceBandProps) {
  return (
    <div className="flex items-center gap-3 text-xs text-text-muted mt-4 pt-3 border-t border-border/60">
      <TrustChip variant={confidence && confidence < 90 ? "warning" : "verified"} label={verifiedBy || "Verified"} />
      {sourceUrl && (
        <span className="flex items-center gap-1">
          Source: <span className="font-medium text-text">{sourceUrl}</span>
        </span>
      )}
      {lastVerified && (
        <>
          <span>•</span>
          <span>{lastVerified}</span>
        </>
      )}
      {confidence && (
        <>
          <span>•</span>
          <span>Confidence: {confidence}%</span>
        </>
      )}
    </div>
  );
}
