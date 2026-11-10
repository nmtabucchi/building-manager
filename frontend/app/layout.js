import "./globals.css";

export const metadata = {
  title: "Building Manager",
  description: "Asistente inteligente para la administración de edificios y consorcios",
};

export default function RootLayout({ children }) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
