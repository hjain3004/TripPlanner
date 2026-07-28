"use client";
import React from 'react';
import { motion } from 'motion/react';
import { useReducedMotionSafe } from "@/lib/motion/use-reduced-motion-safe";

export const AbstractBackground = () => (
  <div className="fixed inset-0 z-[-1] overflow-hidden pointer-events-none bg-bg">
    {/* token-lint-disable-next-line no-inline-svg -- Hand-authored SVG */}
    <svg className="absolute top-[-10%] right-[-5%] w-[800px] h-[800px] opacity-40" viewBox="0 0 800 800" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="400" cy="400" r="400" className="fill-accent-2" />
      <circle cx="400" cy="400" r="399" className="stroke-primary" strokeWidth="2" strokeDasharray="10 20" opacity="0.2" />
    </svg>
    {/* token-lint-disable-next-line no-inline-svg -- Hand-authored SVG */}
    <svg className="absolute bottom-[-20%] left-[-10%] w-[600px] h-[600px] opacity-30" viewBox="0 0 600 600" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M 0 600 A 600 600 0 0 1 600 0" className="stroke-accent-4" strokeWidth="1" />
      <path d="M 100 600 A 500 500 0 0 1 600 100" className="stroke-primary" strokeWidth="1" />
      <path d="M 200 600 A 400 400 0 0 1 600 200" className="stroke-accent-4" strokeWidth="1" strokeDasharray="4 8" />
    </svg>
    <div className="absolute inset-0" style={{ 
      /* token-lint-disable-next-line no-direct-var -- Inline gradient */
      backgroundImage: 'radial-gradient(var(--color-border) 1px, transparent 1px)', 
      backgroundSize: '40px 40px',
      opacity: 0.3,
      maskImage: 'linear-gradient(to bottom, black 0%, transparent 100%)'
    }} />
  </div>
);

export const MonumentIllustration = ({ type }: { type: 'mtFuji' | 'temple' | 'tower' | 'synergy' | 'passport' }) => {
  // Tone-based staggering: Shadows/Base (delay: 0), Midtones (delay: 0.3), Highlights (delay: 0.6), Snow/Details (delay: 0.9)
  const reduced = useReducedMotionSafe();
  const drawTransition = (delay: number) => ({ duration: reduced ? 0 : 0.8, delay: reduced ? 0 : delay, ease: "easeOut" as const });

  if (type === 'mtFuji') {
    return (
      /* token-lint-disable-next-line no-inline-svg -- Hand-authored SVG */
      <svg className="w-full h-56 bg-accent-2/30" viewBox="0 0 400 220" fill="none" xmlns="http://www.w3.org/2000/svg">
        <motion.path initial={{ opacity: 0 }} animate={{ opacity: 0.2 }} transition={drawTransition(0)} d="M -20 180 Q 50 140 120 180 T 260 170 T 420 180 L 420 220 L -20 220 Z" className="fill-primary" />
        <motion.path initial={{ opacity: 0 }} animate={{ opacity: 0.95 }} transition={drawTransition(0.1)} d="M -30 220 L 200 40 L 430 220 Z" className="fill-primary" />
        <motion.path initial={{ opacity: 0 }} animate={{ opacity: 0.5 }} transition={drawTransition(0.3)} d="M 40 110 Q 70 80 120 100 Q 160 90 200 120" className="stroke-border" strokeWidth="12" strokeLinecap="round" />
        <motion.path initial={{ opacity: 0 }} animate={{ opacity: 0.4 }} transition={drawTransition(0.4)} d="M 250 80 Q 280 60 320 70 Q 360 60 380 90" className="stroke-border" strokeWidth="8" strokeLinecap="round" />
        <motion.circle initial={{ opacity: 0 }} animate={{ opacity: 0.9 }} transition={drawTransition(0.6)} cx="200" cy="90" r="45" className="fill-accent-4" />
        <motion.path initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={drawTransition(0.8)} d="M 129 105 L 200 40 L 271 105 L 245 125 L 225 95 L 205 130 L 175 100 L 155 125 Z" className="fill-bg" />
        <motion.path initial={{ opacity: 0 }} animate={{ opacity: 0.8 }} transition={drawTransition(0.9)} d="M -10 180 Q 30 150 80 170 Q 130 140 180 170" className="stroke-bg" strokeWidth="16" strokeLinecap="round" />
        <motion.path initial={{ opacity: 0 }} animate={{ opacity: 0.8 }} transition={drawTransition(1.0)} d="M 220 190 Q 260 160 310 180 Q 360 150 410 180" className="stroke-bg" strokeWidth="14" strokeLinecap="round" />
        <motion.path initial={{ opacity: 0 }} animate={{ opacity: 0.6 }} transition={drawTransition(1.1)} d="M 40 220 L 45 190 L 50 220 M 60 220 L 65 180 L 70 220 M 340 220 L 345 185 L 350 220 M 360 220 L 365 195 L 370 220" className="stroke-bg" strokeWidth="3" />
      </svg>
    );
  }
  if (type === 'temple') {
    return (
      /* token-lint-disable-next-line no-inline-svg -- Hand-authored SVG */
      <svg className="w-full h-56 bg-accent-2/30" viewBox="0 0 400 220" fill="none" xmlns="http://www.w3.org/2000/svg">
        <motion.path initial={{ opacity: 0 }} animate={{ opacity: 0.15 }} transition={drawTransition(0)} d="M 0 220 Q 30 160 60 220 M 340 220 Q 370 150 400 220" className="fill-primary" />
        <motion.path initial={{ opacity: 0 }} animate={{ opacity: 0.7 }} transition={drawTransition(0.1)} d="M 90 220 L 110 170 L 290 170 L 310 220 Z" className="fill-primary" />
        <motion.rect initial={{ opacity: 0 }} animate={{ opacity: 0.9 }} transition={drawTransition(0.2)} x="130" y="150" width="140" height="20" className="fill-primary" />
        <motion.path initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={drawTransition(0.4)} d="M 80 150 Q 200 120 320 150 L 290 135 L 110 135 Z" className="fill-accent-4" />
        <motion.path initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={drawTransition(0.5)} d="M 100 95 Q 200 65 300 95 L 270 80 L 130 80 Z" className="fill-accent-4" />
        <motion.path initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={drawTransition(0.6)} d="M 115 50 Q 200 20 285 50 L 255 35 L 145 35 Z" className="fill-accent-4" />
        <motion.circle initial={{ opacity: 0 }} animate={{ opacity: 0.7 }} transition={drawTransition(0.8)} cx="320" cy="60" r="30" className="fill-accent-4" />
        <motion.rect initial={{ opacity: 0 }} animate={{ opacity: 0.9 }} transition={drawTransition(0.9)} x="140" y="95" width="120" height="40" className="fill-bg" />
        <motion.rect initial={{ opacity: 0 }} animate={{ opacity: 0.9 }} transition={drawTransition(0.9)} x="155" y="50" width="90" height="30" className="fill-bg" />
        <motion.g initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={drawTransition(1.1)}>
          <line x1="170" y1="95" x2="170" y2="135" className="stroke-primary" strokeWidth="6" />
          <line x1="230" y1="95" x2="230" y2="135" className="stroke-primary" strokeWidth="6" />
          <line x1="180" y1="50" x2="180" y2="80" className="stroke-primary" strokeWidth="5" />
          <line x1="220" y1="50" x2="220" y2="80" className="stroke-primary" strokeWidth="5" />
          <path d="M 195 35 L 200 5 L 205 35 Z" className="fill-primary" />
          <circle cx="200" cy="15" r="4" className="fill-accent-4" />
          <circle cx="200" cy="25" r="5" className="fill-accent-4" />
          <rect x="110" y="160" width="12" height="18" className="fill-accent-4" />
          <rect x="278" y="160" width="12" height="18" className="fill-accent-4" />
        </motion.g>
      </svg>
    );
  }
  if (type === 'tower') {
    return (
      /* token-lint-disable-next-line no-inline-svg -- Hand-authored SVG */
      <svg className="w-full h-56 bg-accent-2/30" viewBox="0 0 400 220" fill="none" xmlns="http://www.w3.org/2000/svg">
        <motion.g initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={drawTransition(0)}>
          <rect x="30" y="160" width="40" height="60" className="fill-primary" opacity="0.15" />
          <rect x="80" y="130" width="35" height="90" className="fill-primary" opacity="0.25" />
          <rect x="280" y="170" width="55" height="50" className="fill-primary" opacity="0.15" />
          <rect x="345" y="120" width="40" height="100" className="fill-primary" opacity="0.25" />
        </motion.g>
        <motion.g initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={drawTransition(0.3)}>
          <path d="M 120 220 L 155 140 L 245 140 L 280 220 Z" className="fill-primary" opacity="0.1" />
          <path d="M 140 220 Q 200 170 260 220" className="fill-accent-2" opacity="0.5" />
          <path d="M 160 120 L 190 40 L 210 40 L 240 120 Z" className="fill-primary" opacity="0.1" />
        </motion.g>
        <motion.g initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={drawTransition(0.6)}>
          <line x1="120" y1="220" x2="155" y2="140" className="stroke-accent-4" strokeWidth="5" />
          <line x1="280" y1="220" x2="245" y2="140" className="stroke-accent-4" strokeWidth="5" />
          <line x1="135" y1="180" x2="265" y2="180" className="stroke-accent-4" strokeWidth="3" />
          <line x1="160" y1="120" x2="190" y2="40" className="stroke-accent-4" strokeWidth="4" />
          <line x1="240" y1="120" x2="210" y2="40" className="stroke-accent-4" strokeWidth="4" />
          <line x1="170" y1="90" x2="230" y2="90" className="stroke-accent-4" strokeWidth="3" />
          <line x1="180" y1="65" x2="220" y2="65" className="stroke-accent-4" strokeWidth="3" />
          <path d="M 165 105 L 230 90 M 170 90 L 235 105" className="stroke-accent-4" strokeWidth="1.5" opacity="0.8" />
          <path d="M 175 75 L 220 65 M 180 65 L 225 75" className="stroke-accent-4" strokeWidth="1.5" opacity="0.8" />
          <line x1="200" y1="40" x2="200" y2="5" className="stroke-accent-4" strokeWidth="3" />
        </motion.g>
        <motion.g initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={drawTransition(0.9)}>
          <rect x="145" y="120" width="110" height="20" className="fill-bg stroke-accent-4" strokeWidth="4" />
          <circle cx="200" cy="5" r="3" className="fill-accent-4" />
        </motion.g>
      </svg>
    );
  }
  if (type === 'synergy') {
    return (
      /* token-lint-disable-next-line no-inline-svg -- Hand-authored SVG */
      <svg className="w-full h-32 bg-accent-2/30" viewBox="0 0 400 120" fill="none" xmlns="http://www.w3.org/2000/svg">
        <motion.g initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={drawTransition(0)}>
          <rect x="80" y="20" width="120" height="80" className="fill-primary" opacity="0.8" transform="rotate(-15 140 60)" />
        </motion.g>
        <motion.g initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={drawTransition(0.2)}>
          <rect x="180" y="20" width="120" height="80" className="fill-accent-4" opacity="0.8" transform="rotate(15 240 60)" />
        </motion.g>
        <motion.path initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={drawTransition(0.5)} d="M 190 60 L 210 60 M 200 50 L 200 70" className="stroke-bg" strokeWidth="4" strokeLinecap="round" />
        <motion.circle initial={{ scale: 0, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={drawTransition(0.7)} cx="200" cy="60" r="30" className="stroke-border" strokeWidth="2" strokeDasharray="4 4" fill="none" />
      </svg>
    );
  }
  if (type === 'passport') {
    return (
      /* token-lint-disable-next-line no-inline-svg -- Hand-authored SVG */
      <svg className="w-24 h-32" viewBox="0 0 100 140" fill="none" xmlns="http://www.w3.org/2000/svg">
        <motion.rect initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={drawTransition(0)} x="10" y="10" width="80" height="120" className="fill-primary" />
        <motion.rect initial={{ opacity: 0 }} animate={{ opacity: 0.1 }} transition={drawTransition(0.3)} x="15" y="10" width="4" height="120" className="fill-bg" />
        <motion.circle initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={drawTransition(0.5)} cx="50" cy="50" r="16" className="stroke-accent-4" strokeWidth="1.5" fill="none" />
        <motion.path initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={drawTransition(0.6)} d="M 40 50 Q 50 35 60 50 Q 50 65 40 50" className="stroke-accent-4" strokeWidth="1" fill="none" />
        <motion.path initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={drawTransition(0.7)} d="M 30 100 L 70 100 M 30 110 L 60 110" className="stroke-accent-4" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    );
  }
  return null;
};