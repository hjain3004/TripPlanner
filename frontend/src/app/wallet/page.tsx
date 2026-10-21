import type { Metadata } from "next";

import { SiteHeader } from "@/components/product/site-header";
import { WalletPanel } from "@/components/product/wallet/wallet-panel";

export const metadata: Metadata = {
  title: "Your wallet · TripPlanner",
  description:
    "The cards and points balances saved to your account, and what planning will use.",
};

export default function WalletPage() {
  return (
    <>
      <SiteHeader />
      <main className="mx-auto w-full max-w-[860px] px-[38px] py-10 max-[650px]:px-[18px]">
        <h1 className="text-[28px] font-semibold text-text mb-2">Your wallet</h1>
        <p className="text-[14px] text-text-muted mb-8">
          Cards saved here are the ones planning will optimise against.
        </p>
        <WalletPanel />
      </main>
    </>
  );
}
