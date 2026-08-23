/** @type {import('tailwindcss').Config} */

function color(varName) {
  return ({ opacityValue }) => {
    if (opacityValue !== undefined && opacityValue !== "" && !isNaN(opacityValue)) {
      const pct = Math.round(parseFloat(opacityValue) * 100);
      return `color-mix(in srgb, var(${varName}) ${pct}%, transparent)`;
    }
    return `var(${varName})`;
  };
}

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: color("--paper"),
        panel: color("--panel"),
        surfaceAlt: color("--surface-alt"),
        ink: color("--ink"),
        heading: color("--heading"),
        muted: color("--muted"),
        faint: color("--faint"),
        line: color("--line"),
        lineStrong: color("--line-strong"),
        accent: color("--accent"),
        accentHover: color("--accent-hover"),
        accentSoft: color("--accent-soft"),
        onAccent: color("--on-accent"),
        ok: color("--ok"),
        okSoft: color("--ok-soft"),
        okLine: color("--ok-line"),
        okDot: color("--ok-dot"),
        warn: color("--warn-ink"),
        warnInk: color("--warn-ink"),
        warnSoft: color("--warn-soft"),
        warnLine: color("--warn-line"),
        danger: color("--danger"),
        dangerSoft: color("--danger-soft"),
        tealInk: color("--teal-ink"),
        tealLine: color("--teal-line"),
        tealSoft: color("--teal-soft"),
        solid: color("--solid"),
        onSolid: color("--on-solid"),
      },
    },
  },
  plugins: [],
};
