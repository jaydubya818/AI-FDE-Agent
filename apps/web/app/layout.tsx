import "@fontsource-variable/manrope";
import "@fontsource-variable/newsreader";
import type { Metadata } from "next";
import type { ReactNode } from "react";

import { PRODUCT } from "@/lib/product";

import "./globals.css";

export const metadata: Metadata = {
  title: `${PRODUCT.shortName} · FDLC`,
  description: PRODUCT.description,
};

export default function RootLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  return (
    <html data-scroll-behavior="smooth" lang="en">
      <body>
        <a className="skip-link" href="#main-content">
          Skip to main content
        </a>
        {children}
      </body>
    </html>
  );
}
