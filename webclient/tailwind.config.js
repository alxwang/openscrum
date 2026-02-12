/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Anthropic/Claude-inspired color palette
        background: {
          DEFAULT: '#ffffff',
          dark: '#1a1a1a',
          darker: '#0f0f0f',
        },
        surface: {
          DEFAULT: '#fafafa',
          dark: '#2a2a2a',
        },
        text: {
          primary: '#1a1a1a',
          secondary: '#666666',
          muted: '#999999',
          inverse: '#ffffff',
        },
        accent: {
          DEFAULT: '#2563eb',
          hover: '#1d4ed8',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Monaco', 'monospace'],
      },
      spacing: {
        '18': '4.5rem',
        '88': '22rem',
      },
    },
  },
  plugins: [],
}
