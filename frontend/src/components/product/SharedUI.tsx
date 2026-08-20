"use client";
import React from 'react';
import { ArrowRight } from 'lucide-react';

interface HighlightBoxProps {
  title: string;
  subtitle: string;
  value: React.ReactNode;
  actionLabel: string;
  accent?: 'accent-4' | 'primary';
}

export const HighlightBox = ({ title, subtitle, value, actionLabel, accent = 'accent-4' }: HighlightBoxProps) => {
  const isPrimary = accent === 'primary';
  
  const bgClass = isPrimary ? 'bg-primary/20' : 'bg-accent-4/20';
  const textClass = isPrimary ? 'text-primary' : 'text-accent-4';
  const hoverClass = isPrimary ? 'hover:bg-primary/10' : 'hover:bg-accent-4/10';

  return (
    <div className="relative rounded-2xl border border-border bg-bg shadow-sm overflow-hidden group hover:border-primary/50 transition-all duration-300">
      <div className={`h-2 w-full ${bgClass} relative overflow-hidden`}>
        {/* token-lint-disable-next-line no-inline-svg -- Hand-authored SVG */}
        <svg className={`absolute w-full h-4 -top-1 ${textClass}`} preserveAspectRatio="none" viewBox="0 0 100 10" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M 0 5 Q 5 0, 10 5 T 20 5 T 30 5 T 40 5 T 50 5 T 60 5 T 70 5 T 80 5 T 90 5 T 100 5" />
        </svg>
      </div>
      <div className="p-5 flex flex-col h-full">
        <h4 className="font-ui font-semibold text-lg text-text">{title}</h4>
        <p className="text-sm text-text-muted mt-1 flex-1">{subtitle}</p>
        <div className="mt-6 flex items-center justify-between">
          <div className={`font-medium text-lg ${textClass}`}>{value}</div>
          <button className={`text-xs font-bold uppercase tracking-wider ${textClass} ${hoverClass} px-3 py-1.5 rounded-md transition-colors flex items-center gap-1`}>
            {actionLabel} <ArrowRight className="w-3 h-3" />
          </button>
        </div>
      </div>
    </div>
  );
};