# Vendored libraries

These files are copied into the project so pages load them from this site.
The content security policy stays `default-src 'self'`, with no CDN.
Jay approved both libraries on Nov 3, 2026 for the 3D globe and the GSAP scroll scenes.

| File | Library | Version | Source | License |
|---|---|---|---|---|
| `three.module.min.js` | Three.js | 0.170.0 | `https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.min.js` | MIT, see `three.LICENSE` |
| `gsap.min.js` | GSAP | 3.12.5 | `https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/gsap.min.js` | GSAP standard no-charge license (header of the file) |
| `ScrollTrigger.min.js` | GSAP ScrollTrigger | 3.12.5 | `https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/ScrollTrigger.min.js` | Same as GSAP |

Three.js loads only on the topology page, and only after someone presses **Show 3D globe** (`app/static/js/globe.js`).
GSAP loads only on the home page, only on desktop-class devices with full motion (`effects.js`).
To update a library, download the same file names from the matching version and rerun the tests.
