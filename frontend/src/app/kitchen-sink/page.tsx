"use client";
import React, { useState } from 'react';
import { AnimatePresence } from 'motion/react';
import { Globe, Tags, Star, MapPin, Wallet } from 'lucide-react';
import { resolveTheme } from '@/lib/theme/resolver';
import { AbstractBackground } from '../../components/product/Illustrations';
import { ExploreView } from './views/ExploreView';
import { DealsView } from './views/DealsView';
import { ProofView } from './views/ProofView';
import { ItineraryView } from './views/ItineraryView';
import { WalletView } from './views/WalletView';
import { ProfileView } from './views/ProfileView';
import { RegisterSpecimenView } from './views/RegisterSpecimenView';
import { UiComponentsView } from './views/UiComponentsView';

const PREVIEW_TABS = [
  { id: 'explore', label: 'Explore', icon: Globe },
  { id: 'deals', label: 'Deals', icon: Tags },
  { id: 'proof', label: 'Proof', icon: Star },
  { id: 'itinerary', label: 'Itinerary', icon: MapPin },
  { id: 'register', label: 'Register', icon: null },
  { id: 'wallet', label: 'Wallet Preview', icon: Wallet },
  { id: 'profile', label: 'Profile Preview', icon: null },
  { id: 'ui', label: 'UI', icon: null },
] as const;

type PreviewTab = (typeof PREVIEW_TABS)[number]['id'];

export default function KitchenSinkPage() {
  const [activeTab, setActiveTab] = useState<PreviewTab>('proof');
  const resolved = resolveTheme("JP");
  const activeTabLabel = PREVIEW_TABS.find((tab) => tab.id === activeTab)?.label ?? "Proof";

  return (
    /* token-lint-disable-next-line no-dead-classes -- arbitrary opacity values compile to direct CSS values, not class names */
    <div className={`min-h-screen bg-bg text-text font-ui selection:bg-primary/20 relative z-0 theme-${resolved.globalTheme}`}>
      <AbstractBackground />

      {/* Navbar */}
      {/* token-lint-disable-next-line no-dead-classes -- arbitrary opacity values compile to direct CSS values, not class names */}
      <nav className="sticky top-0 z-50 bg-bg/95 border-b-2 border-border">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 min-h-16 flex items-center justify-between gap-4 py-3">
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 bg-primary flex items-center justify-center text-text-on-primary font-display display-mark shadow-1 text-lg">
              A
            </div>
            <span className="font-display display-mark text-2xl tracking-tight hidden sm:block">Atlas</span>
          </div>

          <div className="lg:hidden flex flex-col gap-1 min-w-0">
            <label htmlFor="preview-section" className="font-mono text-[11px] uppercase tracking-[0.2em] text-text-muted">
              Current preview: {activeTabLabel}
            </label>
            <select
              id="preview-section"
              aria-label="Preview section"
              value={activeTab}
              onChange={(event) => setActiveTab(event.target.value as PreviewTab)}
              /* token-lint-disable-next-line no-dead-classes -- ring-4/ring-primary/30 only exist under the focus-visible: modifier Tailwind emits and the opacity value; neither is matched by this script's plain-selector class scan */
              className="min-h-11 w-[min(58vw,15rem)] border-2 border-border bg-surface px-3 font-ui text-sm font-semibold text-text shadow-1 outline-none focus-visible:ring-4 focus-visible:ring-primary/30"
            >
              {PREVIEW_TABS.map((tab) => (
                <option key={tab.id} value={tab.id}>
                  {tab.label}
                </option>
              ))}
            </select>
          </div>

          <div className="hidden lg:flex items-center gap-4 text-sm font-semibold uppercase tracking-wider">
            {PREVIEW_TABS.map((tab) => {
              const Icon = tab.icon;
              const selected = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => setActiveTab(tab.id)}
                  /* token-lint-disable-next-line no-dead-classes -- ring-4/ring-primary/30 only exist under the focus-visible: modifier Tailwind emits and the opacity value; neither is matched by this script's plain-selector class scan */
                  className={`min-h-11 flex items-center gap-1.5 border-b-2 px-1 outline-none transition-colors focus-visible:ring-4 focus-visible:ring-primary/30 ${
                    selected
                      ? 'text-primary border-primary'
                      : 'text-text-muted border-transparent hover:text-text hover:border-border'
                  }`}
                >
                  {Icon ? <Icon className="w-4 h-4" aria-hidden="true" /> : null}
                  {tab.label}
                </button>
              );
            })}
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
