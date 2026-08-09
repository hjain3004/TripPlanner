import type { Metadata } from "next";
import { Schibsted_Grotesk, Roboto_Mono, Poiret_One } from "next/font/google";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Providers } from "./providers";
import { MSWProvider } from "@/mocks/MSWProvider";
import { PageTransition } from "@/components/product/page-transition";
import { resolveTheme } from "@/lib/theme/resolver";
import "./globals.css";

const poiretOne = Poiret_One({
  subsets: ["latin"],
  variable: "--font-poiret-one",
  weight: ["400"],
});

const schibstedGrotesk = Schibsted_Grotesk({
  subsets: ["latin"],
  variable: "--font-schibsted-grotesk",
  weight: ["400", "500", "600", "700"],
});

const robotoMono = Roboto_Mono({
  subsets: ["latin"],
  variable: "--font-roboto-mono",
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: "TripPlanner",
  description: "A travel planner that knows your credit cards.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // Default to JP for testing the golden Japan pack globally
  const resolved = resolveTheme("JP");
  const themeClass = `theme-${resolved.globalTheme}`;

  return (
    <html
      lang="en"
      className={`${themeClass} ${schibstedGrotesk.variable} ${robotoMono.variable} ${poiretOne.variable}`}
    >
      <body>
        <TooltipProvider>
          <Providers>
            <MSWProvider><main><PageTransition>{children}</PageTransition></main></MSWProvider>
          </Providers>
        </TooltipProvider>
      </body>
    </html>
  );
}
