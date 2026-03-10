/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "#0f172a",
        primary: "#10b981",
        secondary: "#3b82f6",
      }
    },
  },
  plugins: [],
}
