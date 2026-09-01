import "./globals.css";
import { Unbounded, Inter } from "next/font/google";
import { AuthProvider } from "@/lib/auth";
import { ClientProvider } from "@/lib/clients";
import { ThemeProvider, THEME_BOOT_SCRIPT } from "@/lib/theme";

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
    <html lang="es" suppressHydrationWarning>
      <head>
        {/* Corre antes del primer paint: sin esto el tema guardado (o el
            del sistema) recién se aplica cuando React hidrata, y se ve un
            flash del tema oscuro por defecto. Ver lib/theme.jsx. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT_SCRIPT }} />
      </head>
      <body className={`${unbounded.variable} ${inter.variable}`}>
        <ThemeProvider>
          <AuthProvider>
            <ClientProvider>{children}</ClientProvider>
          </AuthProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
