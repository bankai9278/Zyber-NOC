# Vendored libraries

These files are copied into the project so pages load them from this site.
The content security policy stays `default-src 'self'`, with no CDN.

| File | Library | Version | Source | License |
|---|---|---|---|---|
| `gsap.min.js` | GSAP | 3.12.5 | `https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/gsap.min.js` | GSAP standard no-charge license (header of the file) |
| `ScrollTrigger.min.js` | GSAP ScrollTrigger | 3.12.5 | `https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/ScrollTrigger.min.js` | Same as GSAP |

GSAP loads only on the home page, only on desktop-class devices with full motion (`effects.js`).
Three.js was removed on Nov 5, 2026 along with the 3D globe.
To update a library, download the same file names from the matching version and rerun the tests.
