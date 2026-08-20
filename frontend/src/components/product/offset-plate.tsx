import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface OffsetPlateProps {
  children: ReactNode;
  className?: string;
}

export function OffsetPlate({ children, className }: OffsetPlateProps) {
  return (
    <div
      className={cn(
        "relative isolate",
        "before:absolute before:top-[12px] before:left-[12px] before:right-[-12px] before:bottom-[-12px] before:bg-accent-4 before:-z-10",
        className
      )}
    >
      {children}
    </div>
  );
}
