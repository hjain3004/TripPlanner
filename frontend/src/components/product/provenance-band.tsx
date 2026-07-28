interface ProvenanceBandProps {
  sourceUrl?: string;
  lastVerified?: string;
  verifiedBy?: string;
  confidence?: string;
}

export function ProvenanceBand({
  sourceUrl,
  lastVerified,
  verifiedBy,
  confidence,
}: ProvenanceBandProps) {
  return (
    <div className="border-t border-b border-border py-1.5 px-4">
      <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-[11px] leading-relaxed font-mono text-text-muted">
        {sourceUrl && (
          <span>
            source:{" "}
            <span className="text-text-muted">{sourceUrl}</span>
          </span>
        )}
        {lastVerified && (
          <span>
            verified: <span className="text-text-muted">{lastVerified}</span>
          </span>
        )}
        {verifiedBy && (
          <span>
            by: <span className="text-text-muted">{verifiedBy}</span>
          </span>
        )}
        {confidence && (
          <span>
            confidence: <span className="text-text-muted">{confidence}</span>
          </span>
        )}
      </div>
    </div>
  );
}
