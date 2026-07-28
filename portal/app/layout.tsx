import type { Metadata } from "next";
import { headers } from "next/headers";
import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const host = requestHeaders.get("x-forwarded-host") ?? requestHeaders.get("host");
  const protocol = requestHeaders.get("x-forwarded-proto") ?? "https";
  const metadataBase = host ? new URL(`${protocol}://${host}`) : undefined;

  return {
    metadataBase,
    title: "ML Platform Command Center",
    description:
      "A self-service command center for models, runs, deployments, inference, and reviewed GPU evidence.",
    openGraph: {
      title: "ML Platform Command Center",
      description:
        "Operate the complete model lifecycle and inspect reproducible RTX 4080 SUPER evidence.",
      type: "website",
      images: metadataBase ? [{ url: new URL("/og.png", metadataBase).toString() }] : undefined,
    },
    twitter: {
      card: "summary_large_image",
      title: "ML Platform Command Center",
      description:
        "Models, deployments, inference, observability, and GPU evidence in one operational view.",
      images: metadataBase ? [new URL("/og.png", metadataBase).toString()] : undefined,
    },
  };
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-Hant">
      <body>{children}</body>
    </html>
  );
}
