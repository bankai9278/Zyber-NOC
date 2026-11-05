# Fonts

| File | Font | Version | Source | License |
|---|---|---|---|---|
| `space-grotesk-wght.woff2` | Space Grotesk, variable weight 300-700 | 2.0.0 (master branch, commit `03507d0`) | `fonts/woff2/SpaceGrotesk[wght].woff2` in the official repository, https://github.com/floriankarsten/space-grotesk | SIL Open Font License 1.1, copied in `SpaceGrotesk-OFL.txt` |

The font is served from this folder, never from a font CDN, so the content security policy stays `default-src 'self'`. It is used for page headings only (`--font-display` in `site.css`). Body text and labels keep the system fonts.
