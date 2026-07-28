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
  return <span className="tabular-nums font-medium">{formatted}</span>;
};

export const TrustChip = ({ state, verifier }: { state: 'verified' | 'warning' | 'needs-verification', verifier?: string }) => {
  const config = {
    verified: { icon: ShieldCheck, class: 'bg-primary/10 text-primary border-primary/20' },
    warning: { icon: AlertCircle, class: 'bg-lacquer/10 text-lacquer border-lacquer/20' },
    'needs-verification': { icon: Info, class: 'bg-accent text-accent-foreground border-accent-foreground/20' }
  };
  const { icon: Icon, class: className } = config[state];
  return (
    <div className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium border ${className}`}>
      <Icon className="w-3.5 h-3.5" />
      <span>{state === 'needs-verification' ? 'Unverified' : verifier || 'Verified'}</span>
    </div>
  );
};

export const ProvenanceBand = ({ source, date, verifier, confidence, state }: any) => (
  <div className="flex items-center gap-3 text-xs text-muted-foreground mt-4 pt-3 border-t border-border/60">
    <TrustChip state={state} verifier={verifier} />
    <span className="flex items-center gap-1">Source: <span className="font-medium text-foreground">{source}</span></span>
    <span>•</span>
    <span>{date}</span>
    <span>•</span>
    <span>Confidence: {confidence}%</span>
  </div>
);

export const NotchLabel = ({ children }: { children: React.ReactNode }) => (
  <div className="relative pl-3 py-1 my-2 inline-block">
    <div className="absolute left-0 top-0 bottom-0 w-1 bg-lacquer rounded-full" />
    <span className="text-sm font-medium text-lacquer tracking-wide uppercase">{children}</span>
  </div>
);

export const WhyThis = ({ title, children }: { title: string, children: React.ReactNode }) => {
  const [isOpen, setIsOpen] = useState(false);
  return (
    <div className="mt-4">
      <button 
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 text-sm font-medium text-primary hover:opacity-80 transition-opacity bg-primary/5 px-3 py-2 rounded-lg w-full"
      >
        <Info className="w-4 h-4" />
        {title}
        <motion.div animate={{ rotate: isOpen ? 180 : 0 }} className="ml-auto">
          <ChevronDown className="w-4 h-4" />
        </motion.div>
      </button>
      <AnimatePresence>
        {isOpen && (
          <motion.initial animate={{ height: 'auto', opacity: 1 }} initial={{ height: 0, opacity: 0 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
            <div className="p-3 text-sm text-muted-foreground leading-relaxed bg-primary/5 rounded-b-lg border-t border-primary/10 text-left">
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
  const bgClass = isPrimary ? 'bg-primary/20' : 'bg-lacquer/20';
  const textClass = isPrimary ? 'text-primary' : 'text-lacquer';
  const hoverClass = isPrimary ? 'hover:bg-primary/10' : 'hover:bg-lacquer/10';

  return (
    <div className="relative rounded-2xl border border-border bg-card shadow-sm overflow-hidden group hover:border-primary/50 transition-all duration-300">
      <div className={`h-2 w-full ${bgClass} relative overflow-hidden`}>
        <svg className={`absolute w-full h-4 -top-1 ${textClass}`} preserveAspectRatio="none" viewBox="0 0 100 10" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M 0 5 Q 5 0, 10 5 T 20 5 T 30 5 T 40 5 T 50 5 T 60 5 T 70 5 T 80 5 T 90 5 T 100 5" />
        </svg>
      </div>
      <div className="p-5 flex flex-col h-full">
        <h4 className="font-display font-bold text-lg text-foreground">{title}</h4>
        <p className="text-sm text-muted-foreground mt-1 flex-1">{subtitle}</p>
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