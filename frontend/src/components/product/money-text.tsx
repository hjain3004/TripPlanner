interface MoneyTextProps {
  minor: number;
  currency?: string;
  className?: string;
}

export function MoneyText({ minor, currency = "INR", className }: MoneyTextProps) {
  const major = minor / 100;
  const formatted = new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(major);

  return <span className={`tabular-nums ${className ?? ""}`}>{formatted}</span>;
}
