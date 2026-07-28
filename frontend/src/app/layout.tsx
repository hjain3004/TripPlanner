import type { Metadata } from "next";
import { Bodoni_Moda, Schibsted_Grotesk, Roboto_Mono } from "next/font/google";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Providers } from "./providers";
import { MSWProvider } from "@/mocks/MSWProvider";
import { PageTransition } from "@/components/product/page-transition";
import "./globals.css";

const bodoniModa = Bodoni_Moda({
  subsets: ["latin"],
  variable: "--font-bodoni-moda",
  axes: ["opsz"],
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
  return (
    <html
      lang="en"
      className={`theme-singapore ${bodoniModa.variable} ${schibstedGrotesk.variable} ${robotoMono.variable}`}
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
