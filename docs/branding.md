# Branding colors

The app uses the logo-inspired red palette for links, primary actions, focus
indicators, and selected states. Theme tokens are defined in
`src/shop/static/shop/css/tokens.css`:

| Token | Light | Dark |
| --- | --- | --- |
| `--accent` | `#b72a3c` | `#ff7d8a` |
| `--accent-hover` | `#8f1f2f` | `#ff9aa3` |
| `--accent-active` | `#711725` | `#ffadb6` |
| `--on-accent` | `#ffffff` | `#000000` |
| `--focus-ring` | `#b72a3c` | `#ff7d8a` |

The darker light-theme reds and brighter dark-theme reds preserve contrast on
their respective surfaces. Focused checks verify WCAG AA text contrast for
accents and primary-button text, plus 3:1 contrast for focus indicators.
