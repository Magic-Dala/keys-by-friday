import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Keys by Friday — Find a home worth moving for",
  description:
    "A renter-controlled AI agent that finds, verifies, and compares Bay Area rental homes.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
