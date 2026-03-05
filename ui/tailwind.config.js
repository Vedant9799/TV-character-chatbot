/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      animation: {
        blink: 'blink 0.7s step-end infinite',
        fadeIn: 'fadeIn 0.18s ease both',
        slideUp: 'slideUp 0.18s ease both',
      },
      keyframes: {
        blink: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0' },
        },
        fadeIn: {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        slideUp: {
          from: { opacity: '0', transform: 'translateY(8px)' },
          to:   { opacity: '1', transform: 'translateY(0)' },
        },
      },
      colors: {
        app: {
          bg:       '#0f1117',
          surface:  '#1a1d27',
          surface2: '#22263a',
          border:   '#2e3150',
        },
      },
    },
  },
  plugins: [],
}
