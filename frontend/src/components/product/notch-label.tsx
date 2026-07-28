import { cn } from "@/lib/utils";

interface NotchLabelProps {
  children: string;
  className?: string;
}

export function NotchLabel({ children, className }: NotchLabelProps) {
  return (
    <span
      className={cn(
        "inline-block text-[10px] font-medium uppercase tracking-wider text-accent-4 border-l-2 border-accent-4 pl-1.5 leading-none",
        className
      )}
    >
      {children}
    </span>
  );
}
