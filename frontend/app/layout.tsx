import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Keys by Friday",
  description: "AI rental search agent",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
