/**
 * Tailwind config — Xynn Trading Command Center (dark-first).
 *
 * Catatan: Tailwind v4 bisa berjalan config-less, tetapi kita simpan config ini
 * agar shadcn CLI & tooling lain mengenali proyek ini sebagai Tailwind project,
 * sekaligus tempat menaruh token extend di masa depan.
 *
 * @type {import('tailwindcss').Config}
 */
module.exports = {
  darkMode: 'class',
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './lib/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {},
  },
  plugins: [],
};
