import React from 'react';
import { motion } from 'motion/react';
import { ResultsView } from '@/components/product/results-view';
import { japanVisualFixture } from '@/mocks/japan-visual-fixture';
import { resolveTheme } from '@/lib/theme/resolver';
import { JAPAN_ATLAS_STAMP } from '@/lib/design/philatelic-assets';

export function RegisterSpecimenView() {
  const resolved = resolveTheme(japanVisualFixture.primaryCountryCode);

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.3 }}
      className={`space-y-8 pb-24 max-w-3xl mx-auto theme-${resolved.globalTheme}`}
    >
      <div className="space-y-3 border-2 border-border bg-surface p-5 shadow-1">
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-text-muted">
          Frontend visual fixture · sample data
        </p>
        <h2 className="text-2xl font-ui font-semibold">Japan results preview</h2>
        <p className="text-text-muted">
          This preview uses a type-valid sample report for composition testing. It does not claim live
          prices, award availability, account sync, or booked inventory.
        </p>
      </div>

      <ResultsView
        report={japanVisualFixture.report}
        destinationArtifact={{
          asset: JAPAN_ATLAS_STAMP,
          routeLabel: `${japanVisualFixture.report.trip_spec.origin_city} → ${japanVisualFixture.report.trip_spec.destination_city}`,
          dateLabel: japanVisualFixture.report.trip_spec.start_date,
          issued: true,
        }}
      />
    </motion.div>
  );
}
