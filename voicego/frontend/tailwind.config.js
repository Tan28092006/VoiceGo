/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'grab-green': '#00B14F',
        'grab-green-dark': '#009040',
        'grab-yellow': '#F5C518',
        'grab-yellow-light': '#F7D34A',
        'surface-card': '#1c1c1e',
        'surface-elevated': '#2c2c2e',
        'success-bg': 'rgba(0, 177, 79, 0.1)',
        'success-border': 'rgba(0, 177, 79, 0.4)',
        'danger': '#ff3b30'
      },
      keyframes: {
        'fade-in-up': {
          '0%': { opacity: '0', transform: 'translateY(20px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'pulse-glow': {
          '0%, 100%': { opacity: '1', transform: 'scale(1)', boxShadow: '0 0 0 0 rgba(0, 177, 79, 0.4)' },
          '50%': { opacity: '0.8', transform: 'scale(1.05)', boxShadow: '0 0 20px 10px rgba(0, 177, 79, 0.2)' },
        },
        'check-pop': {
          '0%': { transform: 'scale(0.5)', opacity: '0' },
          '50%': { transform: 'scale(1.2)' },
          '100%': { transform: 'scale(1)', opacity: '1' },
        },
        'shake': {
          '0%, 100%': { transform: 'translateX(0)' },
          '25%': { transform: 'translateX(-10px)' },
          '75%': { transform: 'translateX(10px)' },
        }
      },
      animation: {
        'fade-in-up': 'fade-in-up 0.4s ease-out forwards',
        'pulse-glow': 'pulse-glow 2s infinite',
        'check-pop': 'check-pop 0.5s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards',
        'shake': 'shake 0.4s ease-in-out',
      }
    },
  },
  plugins: [],
}
