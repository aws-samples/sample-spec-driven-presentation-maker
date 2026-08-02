// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import type { Metadata } from "next"
import { Bricolage_Grotesque, Fraunces, Geist_Mono } from "next/font/google"
import Script from "next/script"
import { Toaster } from "@/components/ui/sonner"
import { AppearanceProvider } from "@/components/AppearanceProvider"
import { LocaleProvider } from "@/i18n/LocaleProvider"
import "./globals.css"

const bricolage = Bricolage_Grotesque({
  variable: "--font-bricolage",
  subsets: ["latin"],
  display: "swap",
})

const fraunces = Fraunces({
  variable: "--font-fraunces",
  subsets: ["latin"],
  display: "swap",
})

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
  display: "swap",
})

const textScaleScript = `try{const p=JSON.parse(localStorage.getItem("sdpm-prefs")||"{}");const s=[90,100,110,125].includes(p.textScale)?p.textScale:100;document.documentElement.style.fontSize=s+"%"}catch{}`

export const metadata: Metadata = {
  title: "spec-driven-presentation-maker",
  description: "AI-powered presentation builder",
  manifest: "/manifest.json",
  other: {
    "mobile-web-app-capable": "yes",
    "apple-mobile-web-app-capable": "yes",
    "apple-mobile-web-app-status-bar-style": "black-translucent",
  },
}

export const viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover" as const,
  themeColor: "#1a1a1c",
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: textScaleScript }} />
      </head>
      <body className={`${bricolage.variable} ${fraunces.variable} ${geistMono.variable} font-sans antialiased`}>
        {/* Noise texture overlay */}
        <div
          aria-hidden="true"
          className="fixed inset-0 pointer-events-none z-0"
          style={{
            opacity: "var(--noise-opacity)",
            backgroundImage: "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E\")",
            backgroundSize: "256px",
          }}
        />
        {/* Theme-aware ambient studio light */}
        <div
          aria-hidden="true"
          className="fixed inset-0 pointer-events-none z-0"
          style={{ background: "var(--glow)" }}
        />
        <AppearanceProvider>
          <LocaleProvider>
            {children}
            <Toaster position="bottom-right" />
          </LocaleProvider>
        </AppearanceProvider>
        <Script
          id="sw-register"
          strategy="afterInteractive"
        >{`if("serviceWorker"in navigator)window.addEventListener("load",()=>navigator.serviceWorker.register("/sw.js"))`}</Script>
      </body>
    </html>
  )
}
