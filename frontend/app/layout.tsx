import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TieOut — Settlement Close Agent",
  description: "Deterministic settlement close agent with a proof-carrying engine",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <header className="topbar">
          <div className="topbar-inner">
            <div className="logo">T</div>
            <div className="brand">
              TieOut<span>settlement close agent</span>
            </div>
            <div className="topbar-right">
              <span className="dot" />
              deterministic spine · proofs P1–P6
            </div>
          </div>
        </header>
        {children}
      </body>
    </html>
  );
}
