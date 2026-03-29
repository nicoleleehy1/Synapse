/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      colors: {
        background: '#ffffff',
        foreground: '#0a0a0a',
        primary:    '#111111',
        secondary:  '#f4f4f4',
        muted:      '#f0f0f0',
        accent:     '#eeeeee',
        border:     '#e2e2e2',
        'chart-1':  '#d4d4d4',
        'chart-2':  '#a3a3a3',
        'chart-3':  '#525252',
        'chart-4':  '#404040',
        'chart-5':  '#1a1a1a',
      },
      fontSize: {
        '2xs': ['0.65rem', { lineHeight: '1rem' }],
      },
    },
  },
  plugins: [],
}
