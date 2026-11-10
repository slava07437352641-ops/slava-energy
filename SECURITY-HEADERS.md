# Security headers

Checked live against `https://slava.it.com/` on 2026-09-25 (`curl -sI`).

## What's already there

- `strict-transport-security: max-age=31556952` -- HSTS, enabled automatically by
  GitHub Pages once HTTPS is enforced for the custom domain. Nothing to do here.

## What was missing, and what was fixed

GitHub Pages is a static host: there is no server config, no `_headers` file
support (unlike Netlify/Vercel/Cloudflare Pages), and no way to set arbitrary
HTTP response headers. The only lever available is the HTML itself.

Added to `index.html`:

- **Content-Security-Policy** (via `<meta http-equiv>`): `default-src 'self';
  img-src 'self' https: data:; style-src 'self'; script-src 'self'; connect-src
  'self'; base-uri 'none'; form-action 'self';`
  - `img-src` allows any `https:` origin because ~64 records display a
    `previewImage` pulled directly from the linked news article's own OG image
    (arbitrary external domains by design, never a fixed list) -- restricting
    this to `'self'` would break those images.
  - Everything else on the page (scripts, styles, data fetches) is same-origin,
    so those directives are locked to `'self'`.
- **Referrer-Policy** (via `<meta name="referrer">`): `strict-origin-when-cross-origin`.
  This matches current browser defaults already, so it's a no-op in practice,
  but makes the intent explicit rather than implicit.

## What can't be fixed without changing hosting

Three protections require a *real* HTTP response header -- the CSP spec
explicitly ignores `frame-ancestors` (and `sandbox`, `report-uri`) when
delivered via `<meta>`, and `X-Frame-Options`, `X-Content-Type-Options` and
`Permissions-Policy` have no `<meta>` equivalent at all. None of these are
achievable on GitHub Pages as currently hosted:

- `X-Frame-Options: DENY` / `Content-Security-Policy: frame-ancestors 'none'`
  (clickjacking protection)
- `X-Content-Type-Options: nosniff` (stops MIME-sniffing)
- `Permissions-Policy` (disables unused browser features like camera/mic/geolocation)

**Hosting-supported fix, without migrating anywhere:** put a free Cloudflare
proxy in front of the existing `slava.it.com` custom domain (Cloudflare stays
free at any traffic level for this use case; GitHub Pages keeps serving the
content unchanged). Cloudflare's free tier lets you add response headers via
**Rules -> Transform Rules -> Modify Response Header**, with no code and no
new deployment pipeline -- add the three headers above there.

**Alternative:** migrate static hosting to a provider with native header
config (Cloudflare Pages, Netlify, Vercel all support a plain headers file in
the repo, e.g. `_headers` or `vercel.json`). This is a bigger change (new
deploy target, new DNS) and only worth it if GitHub Pages becomes limiting for
other reasons too -- the Cloudflare-proxy option above solves the header gap
on its own.
