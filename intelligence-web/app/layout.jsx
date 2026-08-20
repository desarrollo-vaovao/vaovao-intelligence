import "./globals.css";
import { Unbounded, Inter } from "next/font/google";
import { AuthProvider } from "@/lib/auth";
import { ClientProvider } from "@/lib/clients";

const unbounded = Unbounded({
  subsets: ["latin"],
  weight: ["400", "500", "700"],
  variable: "--font-unbounded",
  display: "swap",
});
const inter = Inter({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata = {
  title: "VaoVao Intelligence",
  description: "Consola de operaciones — VaoVao",
};

export default function RootLayout({ children }) {
  return (
    <html lang="es">
      <body className={`${unbounded.variable} ${inter.variable}`}>
        <AuthProvider>
          <ClientProvider>{children}</ClientProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
