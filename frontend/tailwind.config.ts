import type { Config } from "tailwindcss";

// Single source of truth for the app's look -- change a color or radius here
// and it updates everywhere, since every component styles itself with these
// Tailwind tokens (bg-celadon, text-hunter, rounded-card, ...) instead of
// one-off hex values scattered through JSX.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "media",
  theme: {
    extend: {
      colors: {
        // The user edition's palette (CLAUDE.md section 6.3).
        celadon: {
          light: "#C3DEC6",
          DEFAULT: "#A1CCA5",
          dark: "#7FB686",
        },
        hunter: {
          light: "#577A5A",
          DEFAULT: "#415D43",
          dark: "#2E422F",
        },
      },
      borderRadius: {
        card: "0.75rem",
      },
    },
  },
  plugins: [],
} satisfies Config;
