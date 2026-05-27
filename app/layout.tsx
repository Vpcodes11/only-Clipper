import React from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { Film, LayoutDashboard, UploadCloud } from "lucide-react";
import "./globals.css";

export const metadata: Metadata = {
  title: "Only Clipper — Core Video Clipping Engine",
  description: "Brutally simple and reliable AI short clip generator.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <div className="app-container">
          {/* Reusable Sidebar Navigation */}
          <aside className="app-sidebar">
            <Link href="/dashboard" className="brand-logo">
              <Film size={24} />
              <span>Only Clipper</span>
            </Link>

            <nav className="sidebar-nav">
              <Link href="/dashboard" className="nav-item">
                <LayoutDashboard size={18} />
                <span>Dashboard</span>
              </Link>
              <Link href="/upload" className="nav-item">
                <UploadCloud size={18} />
                <span>New Project</span>
              </Link>
            </nav>
          </aside>

          {/* Core App View */}
          <main className="app-content">
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
