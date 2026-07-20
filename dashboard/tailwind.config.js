/** @type {import('tailwindcss').Config} */
export default {
  // Dark mode follows the OS setting (prefers-color-scheme), matching the
  // palette's light/dark CSS variables. PRD §9.2: work in both light and dark.
  darkMode: "media",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: { extend: {} },
  plugins: [],
};
