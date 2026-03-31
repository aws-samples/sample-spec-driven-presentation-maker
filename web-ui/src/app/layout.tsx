// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import type { Metadata } from "next"
import { Geist } from "next/font/google"
import Script from "next/script"
import { Toaster } from "@/components/ui/sonner"
import "./globals.css"

const geist = Geist({
  variable: "--font-geist",
  subsets: ["latin"],
})

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
  themeColor: "#1a1a1f",
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en">
      <body className={`${geist.variable} font-sans antialiased`}>
        {/* Noise texture overlay */}
        <div
          aria-hidden="true"
          className="fixed inset-0 pointer-events-none z-0 opacity-[0.025]"
          style={{
            backgroundImage: "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E\")",
            backgroundSize: "256px",
          }}
        />
        {/* Ambient teal glow */}
        <div
          aria-hidden="true"
          className="fixed pointer-events-none z-0"
          style={{
            top: "-40%",
            left: "30%",
            width: "80%",
            height: "80%",
            background: "radial-gradient(ellipse, oklch(0.75 0.14 185 / 3%) 0%, transparent 60%)",
          }}
        />
        {children}
        <Toaster position="bottom-right" />
        <Script
          id="sw-register"
          strategy="afterInteractive"
        >{`if("serviceWorker"in navigator)window.addEventListener("load",()=>navigator.serviceWorker.register("/sw.js"))`}</Script>
      </body>
    </html>
  )
}
