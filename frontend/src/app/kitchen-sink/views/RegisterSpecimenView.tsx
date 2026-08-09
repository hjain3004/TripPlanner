import React from 'react';
import { motion } from 'motion/react';
import { fixtureHandlers } from '@/mocks/handlers';
import { VerdictHeader } from '@/components/product/verdict-header';
import { DecisionLedger } from '@/components/product/decision-ledger';
import { PaymentStrategyCard } from '@/components/product/payment-strategy-card';
import { TransferPlanPanel } from '@/components/product/transfer-plan-panel';
import { ItineraryTimeline } from '@/components/product/itinerary-timeline';

export function RegisterSpecimenView() {
  const report = fixtureHandlers.redeemReport();

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.3 }}
      className="space-y-12 pb-24 max-w-2xl mx-auto"
    >
      <div className="space-y-4">
        <h2 className="text-2xl font-display font-bold">Issue Register Specimen</h2>
        <p className="text-text-muted">
          All §2 components rendered in their register-issue form, proving they correctly receive the inverted tokens.
        </p>
      </div>

      <section>
        <h3 className="text-lg font-medium text-text-muted mb-4">VerdictHeader</h3>
        <VerdictHeader 
          totals={report.budget_totals} 
          destination={report.trip_spec.destination_city} 
          days={5} 
          confidence={report.confidence} 
        />
      </section>

      <section>
        <h3 className="text-lg font-medium text-text-muted mb-4">DecisionLedger & LedgerRow</h3>
        <DecisionLedger
          title="Payment Plan"
          items={[
            {
              id: 'row1',
              label: 'Flight Booking',
              value: '₹120,000',
              cost: '₹114,000',
              notch: 'Best Value',
              dominant: true
            },
            {
              id: 'row2',
              label: 'Hotel Reservation',
              value: '₹80,000',
              cost: '₹80,000',
            }
          ]}
        />
      </section>

      <section>
        <h3 className="text-lg font-medium text-text-muted mb-4">PaymentStrategyCard</h3>
        <PaymentStrategyCard 
          assignment={{
            line_id: "flight_001",
            line: {
              id: "flight_001",
              label: "DEL→SIN flights (2 pax)",
              category: "flights",
              amount_minor: 12000000,
              currency: "INR",
              available_channels: ["direct_airline"]
            },
            card_id: "hdfc-infinia",
            channel: "direct_airline",
            offers_applied: [{ offer_id: "5% cashback", discount_minor: 600000 }],
            points_earned: 5000,
            points_value_minor: 500000,
            forex_fee_minor: 0,
            benefit_minor: 1100000,
            action_sentence: "Book with HDFC Infinia",
            explanation: ["Infinia offers 5% base cashback on SmartBuy flights"]
          }}
        />
      </section>

      <section>
        <h3 className="text-lg font-medium text-text-muted mb-4">TransferPlanPanel</h3>
        {report.transfer_advice && (
          <TransferPlanPanel advice={report.transfer_advice} />
        )}
      </section>

      <section>
        <h3 className="text-lg font-medium text-text-muted mb-4">ItineraryTimeline</h3>
        {report.itinerary && (
          <ItineraryTimeline itinerary={report.itinerary} />
        )}
      </section>

    </motion.div>
  );
}
