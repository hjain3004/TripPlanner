"use client";
import React, { useState } from 'react';
import { AnimatePresence } from 'motion/react';
import { Globe, Tags, Star, MapPin, Wallet, Palette } from 'lucide-react';
import { AbstractBackground } from '../components/product/Illustrations';
import { ExploreView } from './views/ExploreView';
import { DealsView } from './views/DealsView';
import { ProofView } from './views/ProofView';
import { ItineraryView } from './views/ItineraryView';
import { WalletView } from './views/WalletView';
import { ProfileView } from './views/ProfileView';

export default function App() {
  const [activeTab, setActiveTab] = useState<'explore' | 'deals' | 'proof' | 'itinerary' | 'wallet' | 'profile'>('explore');
  const [theme, setTheme] = useState<'theme-japan' | 'theme-singapore'>('theme-japan');

  // Country themes only apply to country-specific views. Platform views stay default.
  const isCountryView = activeTab === 'explore' || activeTab === 'itinerary';
  const activeThemeClass = isCountryView ? theme : 'theme-singapore';

  return (
    <div className={`min-h-screen bg-background text-foreground font-ui selection:bg-primary/20 relative z-0 ${activeThemeClass} transition-colors duration-500`}>
      <AbstractBackground />

      {/* Navbar */}
      <nav className="sticky top-0 z-50 bg-background/80 backdrop-blur-md border-b border-border/50">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-primary rounded-xl flex items-center justify-center text-primary-foreground font-display font-bold shadow-sm text-lg">A</div>
            <span className="font-display font-bold text-2xl tracking-tight hidden sm:block">Atlas</span>
          </div>
          
          <div className="flex items-center gap-4 sm:gap-6 text-xs sm:text-sm font-bold uppercase tracking-wider">
            <button 
              onClick={() => setActiveTab('explore')}
              className={`flex items-center gap-1.5 transition-colors pb-1 border-b-2 ${activeTab === 'explore' ? 'text-lacquer border-lacquer' : 'text-muted-foreground border-transparent hover:text-foreground hover:border-border'}`}
            ><Globe className="w-4 h-4 hidden sm:block" /> Explore</button>
            <button 
              onClick={() => setActiveTab('deals')}
              className={`flex items-center gap-1.5 transition-colors pb-1 border-b-2 ${activeTab === 'deals' ? 'text-primary border-primary' : 'text-muted-foreground border-transparent hover:text-foreground hover:border-border'}`}
            ><Tags className="w-4 h-4 hidden sm:block" /> Deals</button>
            <button 
              onClick={() => setActiveTab('proof')}
              className={`flex items-center gap-1.5 transition-colors pb-1 border-b-2 ${activeTab === 'proof' ? 'text-lacquer border-lacquer' : 'text-muted-foreground border-transparent hover:text-foreground hover:border-border'}`}
            ><Star className="w-4 h-4 hidden sm:block" /> Proof</button>
            <button 
              onClick={() => setActiveTab('itinerary')}
              className={`flex items-center gap-1.5 transition-colors pb-1 border-b-2 ${activeTab === 'itinerary' ? 'text-lacquer border-lacquer' : 'text-muted-foreground border-transparent hover:text-foreground hover:border-border'}`}
            ><MapPin className="w-4 h-4 hidden sm:block" /> Itinerary</button>
            <button 
              onClick={() => setActiveTab('wallet')}
              className={`flex items-center gap-1.5 transition-colors pb-1 border-b-2 ${activeTab === 'wallet' ? 'text-primary border-primary' : 'text-muted-foreground border-transparent hover:text-foreground hover:border-border'}`}
            ><Wallet className="w-4 h-4 hidden sm:block" /> Wallet</button>
            
            {/* Profile Avatar Trigger */}
            <button 
              onClick={() => setActiveTab('profile')}
              className={`w-10 h-10 rounded-full border-2 flex items-center justify-center text-xs font-bold transition-colors ml-2 sm:ml-4
                ${activeTab === 'profile' ? 'bg-lacquer border-lacquer text-background' : 'bg-secondary border-border text-muted-foreground hover:border-primary'}
              `}
            >
              JS
            </button>

            {/* Theme Switcher (Only visible on destination tabs) */}
            <div className={`items-center gap-2 ml-4 pl-4 border-l border-border hidden lg:flex transition-opacity duration-300 ${isCountryView ? 'opacity-100' : 'opacity-30 pointer-events-none'}`}>
              <Palette className="w-4 h-4 text-muted-foreground" />
              <select 
                value={theme}
                onChange={(e) => setTheme(e.target.value as any)}
                className="bg-transparent text-foreground border border-border rounded-md px-2 py-1 outline-none text-[11px] font-mono cursor-pointer"
              >
                <option value="theme-singapore">Singapore</option>
                <option value="theme-japan">Japan</option>
              </select>
            </div>
          </div>
        </div>
      </nav>

      <main className="max-w-6xl mx-auto px-6 py-12">
        <AnimatePresence mode="wait">
          {activeTab === 'explore' && <ExploreView key="explore" />}
          {activeTab === 'deals' && <DealsView key="deals" />}
          {activeTab === 'proof' && <ProofView key="proof" />}
          {activeTab === 'itinerary' && <ItineraryView key="itinerary" />}
          {activeTab === 'wallet' && <WalletView key="wallet" />}
          {activeTab === 'profile' && <ProfileView key="profile" />}
        </AnimatePresence>
      </main>
    </div>
  );
}
