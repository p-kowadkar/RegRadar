/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#0f1419",
        surface: {
          DEFAULT: "#161b22",
          alt: "#1c232c",
          high: "#222b35",
        },
        line: {
          DEFAULT: "#2a323d",
          strong: "#3a4452",
        },
        text: {
          primary: "#e6edf3",
          secondary: "#9da7b3",
          muted: "#6b7682",
        },
        brand: {
          DEFAULT: "#2dd4bf",
          dim: "#0d9488",
        },
        status: {
          ok: "#16a34a",
          warn: "#d97706",
          critical: "#dc2626",
          info: "#2563eb",
        },
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "sans-serif",
        ],
        mono: [
          "JetBrains Mono",
          "ui-monospace",
          "SFMono-Regular",
          "monospace",
        ],
      },
      fontSize: {
        xxs: ["10.5px", { lineHeight: "14px", letterSpacing: "0.04em" }],
      },
      boxShadow: {
        panel: "0 1px 0 rgba(255,255,255,0.02) inset, 0 1px 2px rgba(0,0,0,0.4)",
      },
    },
  },
  plugins: [],
};
