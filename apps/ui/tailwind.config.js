/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        canvas: '#0b0e14',
        panel: '#12161f',
        panelAlt: '#171c27',
        border: '#232a38',
        accent: '#4f8cff',
        accentSoft: '#1c2c4d',
        ok: '#3fb950',
        warn: '#d29922',
        danger: '#f85149',
        muted: '#8b98ab',
      },
      fontFamily: {
        sans: ['Inter', 'Segoe UI', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Cascadia Code', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
};
