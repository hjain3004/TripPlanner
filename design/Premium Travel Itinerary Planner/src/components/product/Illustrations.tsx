import React from 'react';
import { motion } from 'motion/react';

export const AbstractBackground = () => (
  <div className="fixed inset-0 z-[-1] overflow-hidden pointer-events-none bg-background">
    <svg className="absolute top-[-10%] right-[-5%] w-[800px] h-[800px] opacity-40" viewBox="0 0 800 800" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="400" cy="400" r="400" fill="var(--color-secondary)" />
      <circle cx="400" cy="400" r="399" stroke="var(--color-primary)" strokeWidth="2" strokeDasharray="10 20" opacity="0.2" />
    </svg>
    <svg className="absolute bottom-[-20%] left-[-10%] w-[600px] h-[600px] opacity-30" viewBox="0 0 600 600" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M 0 600 A 600 600 0 0 1 600 0" stroke="var(--color-lacquer)" strokeWidth="1" />
      <path d="M 100 600 A 500 500 0 0 1 600 100" stroke="var(--color-primary)" strokeWidth="1" />
      <path d="M 200 600 A 400 400 0 0 1 600 200" stroke="var(--color-lacquer)" strokeWidth="1" strokeDasharray="4 8" />
    </svg>
    <div className="absolute inset-0" style={{ 
      backgroundImage: 'radial-gradient(var(--color-border) 1px, transparent 1px)', 
      backgroundSize: '40px 40px',
      opacity: 0.3,
      maskImage: 'linear-gradient(to bottom, black 0%, transparent 100%)'
    }} />
  </div>
);

export const MonumentIllustration = ({ type }: { type: 'mtFuji' | 'temple' | 'tower' | 'synergy' | 'passport' }) => {
  // Tone-based staggering: Shadows/Base (delay: 0), Midtones (delay: 0.3), Highlights (delay: 0.6), Snow/Details (delay: 0.9)
  const drawTransition = (delay: number) => ({ duration: 0.8, delay, ease: "easeOut" });

  if (type === 'mtFuji') {
    return (
      <svg className="w-full h-56 bg-secondary/30" viewBox="0 0 400 220" fill="none" xmlns="http://www.w3.org/2000/svg">
        {/* Distant mountains */}
        <motion.path initial={{ opacity: 0 }} animate={{ opacity: 0.2 }} transition={drawTransition(0)} d="M -20 180 Q 50 140 120 180 T 260 170 T 420 180 L 420 220 L -20 220 Z" fill="var(--color-primary)" />
        {/* Sun */}
        <motion.circle initial={{ opacity: 0 }} animate={{ opacity: 0.9 }} transition={drawTransition(0.6)} cx="200" cy="90" r="45" fill="var(--color-lacquer)" />
        {/* Clouds behind */}
        <motion.path initial={{ opacity: 0 }} animate={{ opacity: 0.5 }} transition={drawTransition(0.3)} d="M 40 110 Q 70 80 120 100 Q 160 90 200 120" stroke="var(--color-border)" strokeWidth="12" strokeLinecap="round" />
        <motion.path initial={{ opacity: 0 }} animate={{ opacity: 0.4 }} transition={drawTransition(0.4)} d="M 250 80 Q 280 60 320 70 Q 360 60 380 90" stroke="var(--color-border)" strokeWidth="8" strokeLinecap="round" />
        {/* Fuji Main Body */}
        <motion.path initial={{ opacity: 0 }} animate={{ opacity: 0.95 }} transition={drawTransition(0.1)} d="M -30 220 L 200 40 L 430 220 Z" fill="var(--color-primary)" />
        {/* Snow Cap with jagged detailed edges */}
        <motion.path initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={drawTransition(0.8)} d="M 129 105 L 200 40 L 271 105 L 245 125 L 225 95 L 205 130 L 175 100 L 155 125 Z" fill="var(--color-background)" />
        {/* Foreground Clouds */}
        <motion.path initial={{ opacity: 0 }} animate={{ opacity: 0.8 }} transition={drawTransition(0.9)} d="M -10 180 Q 30 150 80 170 Q 130 140 180 170" stroke="var(--color-background)" strokeWidth="16" strokeLinecap="round" />
        <motion.path initial={{ opacity: 0 }} animate={{ opacity: 0.8 }} transition={drawTransition(1.0)} d="M 220 190 Q 260 160 310 180 Q 360 150 410 180" stroke="var(--color-background)" strokeWidth="14" strokeLinecap="round" />
        {/* Pine trees silhouette */}
        <motion.path initial={{ opacity: 0 }} animate={{ opacity: 0.6 }} transition={drawTransition(1.1)} d="M 40 220 L 45 190 L 50 220 M 60 220 L 65 180 L 70 220 M 340 220 L 345 185 L 350 220 M 360 220 L 365 195 L 370 220" stroke="var(--color-background)" strokeWidth="3" />
      </svg>
    );
  }
  if (type === 'temple') {
    return (
      <svg className="w-full h-56 bg-secondary/30" viewBox="0 0 400 220" fill="none" xmlns="http://www.w3.org/2000/svg">
        {/* Sun/Moon */}
        <motion.circle initial={{ opacity: 0 }} animate={{ opacity: 0.7 }} transition={drawTransition(0)} cx="320" cy="60" r="30" fill="var(--color-lacquer)" />
        {/* Silhouette trees */}
        <motion.path initial={{ opacity: 0 }} animate={{ opacity: 0.15 }} transition={drawTransition(0.1)} d="M 0 220 Q 30 160 60 220 M 340 220 Q 370 150 400 220" fill="var(--color-primary)" />
        {/* Stone Base */}
        <motion.path initial={{ opacity: 0 }} animate={{ opacity: 0.7 }} transition={drawTransition(0.2)} d="M 90 220 L 110 170 L 290 170 L 310 220 Z" fill="var(--color-primary)" />
        <motion.rect initial={{ opacity: 0 }} animate={{ opacity: 0.9 }} transition={drawTransition(0.3)} x="130" y="150" width="140" height="20" fill="var(--color-primary)" />
        {/* Tier 1 */}
        <motion.path initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={drawTransition(0.4)} d="M 80 150 Q 200 120 320 150 L 290 135 L 110 135 Z" fill="var(--color-lacquer)" />
        <motion.rect initial={{ opacity: 0 }} animate={{ opacity: 0.9 }} transition={drawTransition(0.5)} x="140" y="95" width="120" height="40" fill="var(--color-background)" />
        <motion.g initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={drawTransition(0.6)}>
          <line x1="170" y1="95" x2="170" y2="135" stroke="var(--color-primary)" strokeWidth="6" />
          <line x1="230" y1="95" x2="230" y2="135" stroke="var(--color-primary)" strokeWidth="6" />
          <rect x="185" y="105" width="30" height="30" fill="var(--color-lacquer)" opacity="0.2" />
        </motion.g>
        {/* Tier 2 */}
        <motion.path initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={drawTransition(0.7)} d="M 100 95 Q 200 65 300 95 L 270 80 L 130 80 Z" fill="var(--color-lacquer)" />
        <motion.rect initial={{ opacity: 0 }} animate={{ opacity: 0.9 }} transition={drawTransition(0.8)} x="155" y="50" width="90" height="30" fill="var(--color-background)" />
        <motion.g initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={drawTransition(0.9)}>
          <line x1="180" y1="50" x2="180" y2="80" stroke="var(--color-primary)" strokeWidth="5" />
          <line x1="220" y1="50" x2="220" y2="80" stroke="var(--color-primary)" strokeWidth="5" />
        </motion.g>
        {/* Tier 3 Roof */}
        <motion.path initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={drawTransition(1.0)} d="M 115 50 Q 200 20 285 50 L 255 35 L 145 35 Z" fill="var(--color-lacquer)" />
        {/* Spire */}
        <motion.g initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={drawTransition(1.1)}>
          <path d="M 195 35 L 200 5 L 205 35 Z" fill="var(--color-primary)" />
          <circle cx="200" cy="15" r="4" fill="var(--color-lacquer)" />
          <circle cx="200" cy="25" r="5" fill="var(--color-lacquer)" />
          <rect x="110" y="160" width="12" height="18" rx="2" fill="var(--color-lacquer)" />
          <rect x="278" y="160" width="12" height="18" rx="2" fill="var(--color-lacquer)" />
        </motion.g>
      </svg>
    );
  }
  if (type === 'tower') {
    return (
      <svg className="w-full h-56 bg-secondary/30" viewBox="0 0 400 220" fill="none" xmlns="http://www.w3.org/2000/svg">
        <motion.g initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={drawTransition(0)}>
          {/* Background Cityscape detailed */}
          <rect x="30" y="160" width="40" height="60" fill="var(--color-primary)" opacity="0.15" />
          <rect x="80" y="130" width="35" height="90" fill="var(--color-primary)" opacity="0.25" />
          <rect x="280" y="170" width="55" height="50" fill="var(--color-primary)" opacity="0.15" />
          <rect x="345" y="120" width="40" height="100" fill="var(--color-primary)" opacity="0.25" />
          <circle cx="97" cy="150" r="2" fill="var(--color-background)" />
          <circle cx="105" cy="165" r="2" fill="var(--color-background)" />
          <circle cx="360" cy="140" r="2" fill="var(--color-background)" />
        </motion.g>
        
        <motion.g initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={drawTransition(0.3)}>
          {/* Tower Base & Arches */}
          <path d="M 120 220 L 155 140 L 245 140 L 280 220 Z" fill="var(--color-primary)" opacity="0.1" />
          <path d="M 140 220 Q 200 170 260 220" fill="var(--color-secondary)" opacity="0.5" />
        </motion.g>

        <motion.g initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={drawTransition(0.6)}>
          <line x1="120" y1="220" x2="155" y2="140" stroke="var(--color-lacquer)" strokeWidth="5" />
          <line x1="280" y1="220" x2="245" y2="140" stroke="var(--color-lacquer)" strokeWidth="5" />
          <line x1="135" y1="180" x2="265" y2="180" stroke="var(--color-lacquer)" strokeWidth="3" />
          
          <line x1="155" y1="120" x2="155" y2="140" stroke="var(--color-lacquer)" strokeWidth="2" />
          <line x1="175" y1="120" x2="175" y2="140" stroke="var(--color-lacquer)" strokeWidth="2" />
          <line x1="195" y1="120" x2="195" y2="140" stroke="var(--color-lacquer)" strokeWidth="2" />
          <line x1="215" y1="120" x2="215" y2="140" stroke="var(--color-lacquer)" strokeWidth="2" />
          <line x1="235" y1="120" x2="235" y2="140" stroke="var(--color-lacquer)" strokeWidth="2" />

          {/* Upper Lattice */}
          <path d="M 160 120 L 190 40 L 210 40 L 240 120 Z" fill="var(--color-primary)" opacity="0.1" />
          <line x1="160" y1="120" x2="190" y2="40" stroke="var(--color-background)" strokeWidth="6" />
          <line x1="160" y1="120" x2="190" y2="40" stroke="var(--color-lacquer)" strokeWidth="4" />
          <line x1="240" y1="120" x2="210" y2="40" stroke="var(--color-background)" strokeWidth="6" />
          <line x1="240" y1="120" x2="210" y2="40" stroke="var(--color-lacquer)" strokeWidth="4" />
          
          {/* Cross bracing */}
          <line x1="170" y1="90" x2="230" y2="90" stroke="var(--color-lacquer)" strokeWidth="3" />
          <line x1="180" y1="65" x2="220" y2="65" stroke="var(--color-lacquer)" strokeWidth="3" />
          <path d="M 165 105 L 230 90 M 170 90 L 235 105" stroke="var(--color-lacquer)" strokeWidth="1.5" opacity="0.8" />
          <path d="M 175 75 L 220 65 M 180 65 L 225 75" stroke="var(--color-lacquer)" strokeWidth="1.5" opacity="0.8" />
          
          {/* Spire */}
          <line x1="200" y1="40" x2="200" y2="5" stroke="var(--color-background)" strokeWidth="6" />
          <line x1="200" y1="40" x2="200" y2="5" stroke="var(--color-lacquer)" strokeWidth="3" />
        </motion.g>

        <motion.g initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={drawTransition(0.9)}>
          {/* Main Observatory */}
          <rect x="145" y="120" width="110" height="20" fill="var(--color-background)" stroke="var(--color-lacquer)" strokeWidth="4" />
          <circle cx="200" cy="5" r="3" fill="var(--color-lacquer)" />
        </motion.g>
      </svg>
    );
  }
  if (type === 'synergy') {
    return (
      <svg className="w-full h-32 bg-secondary/30" viewBox="0 0 400 120" fill="none" xmlns="http://www.w3.org/2000/svg">
        <motion.g initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={drawTransition(0)}>
          <rect x="80" y="20" width="120" height="80" rx="8" fill="var(--color-primary)" opacity="0.8" transform="rotate(-15 140 60)" />
        </motion.g>
        <motion.g initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={drawTransition(0.2)}>
          <rect x="180" y="20" width="120" height="80" rx="8" fill="var(--color-lacquer)" opacity="0.8" transform="rotate(15 240 60)" />
        </motion.g>
        <motion.path initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={drawTransition(0.5)} d="M 190 60 L 210 60 M 200 50 L 200 70" stroke="var(--color-background)" strokeWidth="4" strokeLinecap="round" />
        <motion.circle initial={{ scale: 0, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={drawTransition(0.7)} cx="200" cy="60" r="30" stroke="var(--color-border)" strokeWidth="2" strokeDasharray="4 4" fill="none" />
      </svg>
    );
  }
  if (type === 'passport') {
    return (
      <svg className="w-24 h-32" viewBox="0 0 100 140" fill="none" xmlns="http://www.w3.org/2000/svg">
        <motion.rect initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={drawTransition(0)} x="10" y="10" width="80" height="120" rx="6" fill="var(--color-primary)" />
        <motion.rect initial={{ opacity: 0 }} animate={{ opacity: 0.1 }} transition={drawTransition(0.3)} x="15" y="10" width="4" height="120" fill="var(--color-background)" />
        <motion.circle initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={drawTransition(0.5)} cx="50" cy="50" r="16" stroke="var(--color-lacquer)" strokeWidth="1.5" fill="none" />
        <motion.path initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={drawTransition(0.6)} d="M 40 50 Q 50 35 60 50 Q 50 65 40 50" stroke="var(--color-lacquer)" strokeWidth="1" fill="none" />
        <motion.path initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={drawTransition(0.7)} d="M 30 100 L 70 100 M 30 110 L 60 110" stroke="var(--color-lacquer)" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    );
  }
  return null;
};
