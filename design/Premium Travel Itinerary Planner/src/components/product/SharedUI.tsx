import React, { useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { ShieldCheck, AlertCircle, Info, ChevronDown, ArrowRight } from 'lucide-react';

export const MoneyText = ({ amount, currency = 'USD' }: { amount: number, currency?: string }) => {
  const formatted = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: currency,
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(amount / 100);
  // Rule: Schibsted Grotesk (font-ui) for all money/numbers
  return <span className="tabular-nums font-ui font-semibold">{formatted}</span>;
};

export const TrustChip = ({ state, verifier }: { state: 'verified' | 'warning' | 'needs-verification', verifier?: string }) => {
  const config = {
    verified: { icon: ShieldCheck, class: 'bg-secondary text-primary border-primary/20' },
    warning: { icon: AlertCircle, class: 'bg-lacquer/10 text-lacquer border-lacquer/20' },
    'needs-verification': { icon: Info, class: 'bg-accent text-foreground border-border' }
  };
  const { icon: Icon, class: className } = config[state];
  return (
    <div className={`inline-flex items-center gap-[6px] px-[8px] py-[2px] rounded-none border-l-2 text-[11px] font-mono tracking-wide uppercase ${className}`}>
      <Icon className="w-3 h-3" />
      <span>{state === 'needs-verification' ? 'Unverified' : verifier || 'Verified'}</span>
    </div>
  );
};

export const ProvenanceBand = ({ source, date, verifier, confidence, state }: any) => (
  <div className="flex items-center gap-4 text-[11px] font-mono text-muted-foreground mt-5 pt-4 border-t border-border">
    <TrustChip state={state} verifier={verifier} />
    <span className="flex items-center gap-1 uppercase tracking-wider opacity-70">
      Source: <span className="font-medium text-foreground opacity-100">{source}</span>
    </span>
    <span className="opacity-50">•</span>
    <span className="uppercase tracking-wider opacity-70">{date}</span>
    <span className="opacity-50">•</span>
    <span className="uppercase tracking-wider opacity-70">Conf: {confidence}%</span>
  </div>
);

export const NotchLabel = ({ children }: { children: React.ReactNode }) => (
  <div className="relative pl-[14px] py-[2px] my-2 inline-flex items-center">
    <div className="absolute left-0 top-0 bottom-0 w-[2px] bg-lacquer" />
    <span className="font-mono text-[11px] font-medium text-lacquer tracking-[0.14em] uppercase">{children}</span>
  </div>
);

export const WhyThis = ({ title, children }: { title: string, children: React.ReactNode }) => {
  const [isOpen, setIsOpen] = useState(false);
  return (
    <div className="mt-4 border-t border-border pt-2">
      <button 
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 text-[13px] font-ui font-medium text-primary hover:opacity-80 transition-opacity w-full text-left"
      >
        <Info className="w-3.5 h-3.5" />
        {title}
        <motion.div animate={{ rotate: isOpen ? 180 : 0 }} className="ml-auto">
          <ChevronDown className="w-3.5 h-3.5" />
        </motion.div>
      </button>
      <AnimatePresence>
        {isOpen && (
          <motion.initial animate={{ height: 'auto', opacity: 1 }} initial={{ height: 0, opacity: 0 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
            <div className="pt-3 pb-1 text-[13px] text-muted-foreground leading-[1.6] font-ui">
              {children}
            </div>
          </motion.initial>
        )}
      </AnimatePresence>
    </div>
  );
};

export const HighlightBox = ({ title, subtitle, value, actionLabel, accent = 'lacquer' }: any) => {
  const isPrimary = accent === 'primary';
  const colorVar = isPrimary ? 'var(--primary)' : 'var(--lacquer)';
  const bgClass = isPrimary ? 'bg-primary/5' : 'bg-lacquer/5';
  const textClass = isPrimary ? 'text-primary' : 'text-lacquer';
  const hoverClass = isPrimary ? 'hover:bg-primary/10' : 'hover:bg-lacquer/10';

  return (
    <div className={`relative rounded-none border border-border bg-card shadow-sm hover:shadow-md transition-shadow duration-300`}>
      <div className={`absolute top-0 left-0 bottom-0 w-[3px]`} style={{ backgroundColor: colorVar }} />
      <div className="p-6 flex flex-col h-full pl-8">
        <h4 className="font-ui font-semibold text-[22px] leading-[1.15] text-foreground tracking-[-0.005em]">{title}</h4>
        <p className="text-[14px] text-muted-foreground leading-[1.6] mt-2 flex-1 font-ui">{subtitle}</p>
        <div className="mt-6 flex items-center justify-between pt-4 border-t border-border">
          <div className={`font-ui font-semibold text-[20px] tabular-nums ${textClass}`}>{value}</div>
          <button className={`text-[11px] font-ui font-semibold tracking-wide ${textClass} ${hoverClass} px-3 py-2 rounded-sm transition-colors flex items-center gap-1`}>
            {actionLabel} <ArrowRight className="w-3 h-3" />
          </button>
        </div>
      </div>
    </div>
  );
};