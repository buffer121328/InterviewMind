import type { Metadata } from "next";
import "./globals.css";
import { Toaster } from "sonner";
import { PRODUCT_DESCRIPTION, PRODUCT_NAME } from "@/lib/product";

export const metadata: Metadata = {
  title: PRODUCT_NAME,
  description: PRODUCT_DESCRIPTION,
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body className="antialiased selection:bg-teal-200 selection:text-teal-950">
        {children}
        <Toaster position="top-center" richColors />
      </body>
    </html>
  );
}
