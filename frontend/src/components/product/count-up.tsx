interface CountUpProps {
  valueMinor: number;
  currency?: string;
}

function formatMoney(minor: number, currency: string): string {
  const major = minor / 100;
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(major);
}

export function CountUp({ valueMinor, currency = "INR" }: CountUpProps) {
  return <span className="tabular-nums" data-motion="count-up">{formatMoney(valueMinor, currency)}</span>;
}
