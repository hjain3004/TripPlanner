import { TrustChip } from "./trust-chip";

interface AssumptionsFooterProps {
  assumptions: string[];
  disclaimers?: string[];
  minVerifiedDate?: string;
  footer?: string;
}

export function AssumptionsFooter({ assumptions, disclaimers, minVerifiedDate, footer }: AssumptionsFooterProps) {
  return (
    <div className="text-xs text-text-muted space-y-3 border-t border-border pt-6">
      {assumptions.length > 0 && (
        <div>
          <h3 className="font-medium text-text mb-1">Assumptions</h3>
          <ul className="list-disc list-inside space-y-0.5">
            {assumptions.map((a, i) => <li key={i}>{a}</li>)}
          </ul>
        </div>
      )}
      {disclaimers && disclaimers.length > 0 && (
        <div>
          <h3 className="font-medium text-text mb-1">Important notes</h3>
          <ul className="space-y-0.5">
            {disclaimers.map((d, i) => (
              <li key={i} className="flex items-start gap-1.5">
                <TrustChip variant="needs-verification" label="Note" />
                <span>{d}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {minVerifiedDate && (
        <p className="text-text-muted">
          Data last verified: {minVerifiedDate}
        </p>
      )}
      {footer && (
        <p className="text-center text-text-muted">{footer}</p>
      )}
    </div>
  );
}
