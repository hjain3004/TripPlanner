"use client";
import React, { useState } from 'react';
import { AnimatePresence } from 'motion/react';
import { Globe, Tags, Star, MapPin, Wallet } from 'lucide-react';
import { AbstractBackground } from '../../components/product/Illustrations';
import { ExploreView } from './views/ExploreView';
import { DealsView } from './views/DealsView';
import { ProofView } from './views/ProofView';
import { ItineraryView } from './views/ItineraryView';
import { WalletView } from './views/WalletView';
import { ProfileView } from './views/ProfileView';
import { RegisterSpecimenView } from './views/RegisterSpecimenView';
import { UiComponentsView } from './views/UiComponentsView';

export default function KitchenSinkPage() {
  const [activeTab, setActiveTab] = useState<'explore' | 'deals' | 'proof' | 'itinerary' | 'wallet' | 'profile' | 'register' | 'ui'>('proof');

  return (
    <div className="min-h-screen bg-bg text-text font-ui selection:bg-primary/20 relative z-0 theme-singapore">
      <AbstractBackground />

      {/* Navbar */}
      <nav className="sticky top-0 z-50 bg-bg/80 backdrop-blur-md border-b border-border/50">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-primary rounded-xl flex items-center justify-center text-text-on-primary font-display font-bold shadow-sm text-lg">A</div>
            <span className="font-display font-bold text-2xl tracking-tight hidden sm:block">Atlas</span>
          </div>
          
          <div className="flex items-center gap-4 sm:gap-6 text-xs sm:text-sm font-bold uppercase tracking-wider overflow-x-auto no-scrollbar pb-1">
            <button 
              onClick={() => setActiveTab('explore')}
              className={`flex items-center gap-1.5 transition-colors pb-1 border-b-2 ${activeTab === 'explore' ? 'text-accent-4 border-accent-4' : 'text-text-muted border-transparent hover:text-text hover:border-border'}`}
            ><Globe className="w-4 h-4 hidden lg:block" /> Explore</button>
            <button 
              onClick={() => setActiveTab('deals')}
              className={`flex items-center gap-1.5 transition-colors pb-1 border-b-2 ${activeTab === 'deals' ? 'text-primary border-primary' : 'text-text-muted border-transparent hover:text-text hover:border-border'}`}
            ><Tags className="w-4 h-4 hidden lg:block" /> Deals</button>
            <button 
              onClick={() => setActiveTab('proof')}
              className={`flex items-center gap-1.5 transition-colors pb-1 border-b-2 ${activeTab === 'proof' ? 'text-accent-4 border-accent-4' : 'text-text-muted border-transparent hover:text-text hover:border-border'}`}
            ><Star className="w-4 h-4 hidden lg:block" /> Proof</button>
            <button 
              onClick={() => setActiveTab('itinerary')}
              className={`flex items-center gap-1.5 transition-colors pb-1 border-b-2 ${activeTab === 'itinerary' ? 'text-accent-4 border-accent-4' : 'text-text-muted border-transparent hover:text-text hover:border-border'}`}
            ><MapPin className="w-4 h-4 hidden lg:block" /> Itinerary</button>
            <button 
              onClick={() => setActiveTab('register')}
              className={`flex items-center gap-1.5 transition-colors pb-1 border-b-2 ${activeTab === 'register' ? 'text-accent-4 border-accent-4' : 'text-text-muted border-transparent hover:text-text hover:border-border'}`}
            >Register</button>
            <button 
              onClick={() => setActiveTab('wallet')}
              className={`flex items-center gap-1.5 transition-colors pb-1 border-b-2 ${activeTab === 'wallet' ? 'text-primary border-primary' : 'text-text-muted border-transparent hover:text-text hover:border-border'}`}
            ><Wallet className="w-4 h-4 hidden lg:block" /> Wallet</button>
            
            {/* Profile Avatar Trigger */}
            <button 
              onClick={() => setActiveTab('profile')}
              className={`w-10 h-10 rounded-full border-2 flex items-center justify-center text-xs font-bold transition-colors ml-2 sm:ml-4
                ${activeTab === 'profile' ? 'bg-accent-4 border-accent-4 text-bg' : 'bg-surface-raised border-border text-text-muted hover:border-primary'}
              `}
            >
              JS
            </button>
            <button 
              onClick={() => setActiveTab('ui')}
              className={`flex items-center gap-1.5 transition-colors pb-1 border-b-2 ${activeTab === 'ui' ? 'text-primary border-primary' : 'text-text-muted border-transparent hover:text-text hover:border-border'}`}
            >UI</button>
          </div>
        </div>
      </nav>

      <div className="max-w-6xl mx-auto px-6 py-12">
        <AnimatePresence mode="wait">
          {activeTab === 'explore' && <ExploreView key="explore" />}
          {activeTab === 'deals' && <DealsView key="deals" />}
          {activeTab === 'proof' && <ProofView key="proof" />}
          {activeTab === 'itinerary' && <ItineraryView key="itinerary" />}
          {activeTab === 'register' && <RegisterSpecimenView key="register" />}
          {activeTab === 'wallet' && <WalletView key="wallet" />}
          {activeTab === 'profile' && <ProfileView key="profile" />}
          {activeTab === 'ui' && <UiComponentsView key="ui" />}
        </AnimatePresence>
      </div>
    </div>
  );
}