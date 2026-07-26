"use client";

export function ProgressRing({ progress, size = 32, strokeWidth = 2 }: { progress: number; size?: number; strokeWidth?: number }) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - progress / 100);
  const center = size / 2;

  return (
    <svg className={`w-${size/4} h-${size/4} -rotate-90`} viewBox={`0 0 ${size} ${size}`}>
      <circle cx={center} cy={center} r={radius} fill="none" className="stroke-border" strokeWidth={strokeWidth} />
      <circle
        cx={center} cy={center} r={radius}
        fill="none" className="stroke-primary transition-all"
        strokeWidth={strokeWidth}
        strokeDasharray={`${circumference}`}
        strokeDashoffset={`${offset}`}
        strokeLinecap="round"
      />
    </svg>
  );
}
