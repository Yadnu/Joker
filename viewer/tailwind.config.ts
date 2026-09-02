import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './app/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
    './lib/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      // Late-night broadcast studio palette.
      // Uses rgb(var(--channel) / <alpha-value>) so Tailwind's /opacity
      // modifier syntax (e.g. text-accent/80, bg-violation/10) works.
      colors: {
        base:          'rgb(var(--color-base)          / <alpha-value>)',
        surface:       'rgb(var(--color-surface)       / <alpha-value>)',
        raised:        'rgb(var(--color-raised)        / <alpha-value>)',
        edge:          'rgb(var(--color-edge)          / <alpha-value>)',
        hi:            'rgb(var(--color-hi)            / <alpha-value>)',
        mid:           'rgb(var(--color-mid)           / <alpha-value>)',
        lo:            'rgb(var(--color-lo)            / <alpha-value>)',
        accent:        'rgb(var(--color-accent)        / <alpha-value>)',
        'accent-dim':  'rgb(var(--color-accent-dim)   / <alpha-value>)',
        'accent-glow': 'rgb(var(--color-accent-glow)  / <alpha-value>)',
        violation:     'rgb(var(--color-violation)     / <alpha-value>)',
        live:          'rgb(var(--color-live)          / <alpha-value>)',
      },
      fontFamily: {
        display: ['var(--font-display)', 'sans-serif'],
        mono: ['var(--font-mono)', 'monospace'],
        sans: ['var(--font-sans)', 'sans-serif'],
      },
      boxShadow: {
        'warm-sm': '0 1px 4px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,200,80,0.06)',
        'warm-md': '0 4px 16px rgba(0,0,0,0.6), 0 0 0 1px rgba(255,200,80,0.08)',
        'accent-glow': '0 0 20px rgba(245,158,11,0.25)',
        'violation-glow': '0 0 16px rgba(220,60,40,0.25)',
      },
      animation: {
        'score-fill': 'scoreFill 1s cubic-bezier(0.22, 1, 0.36, 1) forwards',
        'on-air': 'onAir 1.5s ease-in-out infinite',
        'fade-in': 'fadeIn 0.3s ease-out',
        'slide-in': 'slideIn 0.25s ease-out',
      },
      keyframes: {
        scoreFill: {
          '0%': { width: '0%', opacity: '0.6' },
          '100%': { width: 'var(--score-pct)', opacity: '1' },
        },
        onAir: {
          '0%, 100%': { opacity: '1', boxShadow: '0 0 8px rgba(220,38,38,0.8)' },
          '50%': { opacity: '0.5', boxShadow: '0 0 4px rgba(220,38,38,0.3)' },
        },
        fadeIn: {
          from: { opacity: '0', transform: 'translateY(4px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        slideIn: {
          from: { opacity: '0', transform: 'translateX(-8px)' },
          to: { opacity: '1', transform: 'translateX(0)' },
        },
      },
    },
  },
  plugins: [],
}

export default config
