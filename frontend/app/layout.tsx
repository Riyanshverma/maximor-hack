import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "TieOut",
  description: "Deterministic settlement close agent",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
