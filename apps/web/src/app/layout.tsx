import type { Metadata } from "next";
import { Instrument_Sans, JetBrains_Mono } from "next/font/google";
import { Suspense, type ReactNode } from "react";
import { Providers } from "./providers";
import "./globals.css";

// Self-hosted at build time by next/font: no request to Google from the reviewer's browser.
const sans = Instrument_Sans({ subsets: ["latin"], variable: "--font-sans", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = { title: "Ledgerline", description: "Review invoices the agent couldn't settle on its own." };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`}>
      <body><Suspense fallback={null}><Providers>{children}</Providers></Suspense></body>
    </html>
  );
}
