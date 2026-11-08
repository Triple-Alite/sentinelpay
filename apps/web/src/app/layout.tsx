import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SentinelPay | Trust Every Transaction",
  description: "A security workspace for Web3 payment monitoring and risk assessment.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
