/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        pixel: ['"Press Start 2P"', 'monospace'],
      },
      animation: {
        blink:     'blink 0.7s step-end infinite',
        fadeIn:    'fadeIn 0.22s ease both',
        slideUp:   'slideUp 0.24s ease both',
        slideDown: 'slideDown 0.24s ease both',
        scaleIn:   'scaleIn 0.2s ease both',
        float:     'float 4s ease-in-out infinite',
        shimmer:   'shimmer 2.5s linear infinite',
      },
      keyframes: {
        blink: {
          '0%, 100%': { opacity: '1' },
          '50%':       { opacity: '0' },
        },
        fadeIn: {
          from: { opacity: '0' },
          to:   { opacity: '1' },
        },
        slideUp: {
          from: { opacity: '0', transform: 'translateY(10px)' },
          to:   { opacity: '1', transform: 'translateY(0)' },
        },
        slideDown: {
          from: { opacity: '0', transform: 'translateY(-10px)' },
          to:   { opacity: '1', transform: 'translateY(0)' },
        },
        scaleIn: {
          from: { opacity: '0', transform: 'scale(0.94)' },
          to:   { opacity: '1', transform: 'scale(1)' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%':      { transform: 'translateY(-7px)' },
        },
        shimmer: {
          '0%':   { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition:  '200% 0' },
        },
      },
      colors: {
        app: {
          bg:         '#070709',
          surface:    '#0e0e12',
          surface2:   '#16161c',
          border:     '#222228',
          'border-hi': '#2e2e38',
        },
      },
    },
  },
  plugins: [],
}
