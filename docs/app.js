/* ============================================================
   Poke Research — frontend app (vanilla JS, no build step)
   Loads ./data/*.json, hash routing, live price model recompute.
   ============================================================ */
'use strict';

/* ---------- tiny DOM helpers ---------- */
const $  = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    if (k === 'class') node.className = v;
    else if (k === 'html') node.innerHTML = v;
    else if (k === 'text') node.textContent = v;
    else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2), v);
    else if (k === 'dataset') Object.assign(node.dataset, v);
    else node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) {
    if (c == null) continue;
    node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
  }
  return node;
}

/* ---------- formatting ---------- */
const USD = (n) => (n == null || Number.isNaN(n))
  ? '—'
  : '$' + Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const USD0 = (n) => (n == null || Number.isNaN(n))
  ? '—'
  : '$' + Number(n).toLocaleString('en-US', { maximumFractionDigits: 0 });
const PCT = (n, digits = 1) => (n == null || Number.isNaN(n)) ? '—' : (n * 100).toFixed(digits) + '%';
const signedPct = (n, digits = 1) => {
  if (n == null || Number.isNaN(n)) return '—';
  const v = n * 100;
  return (v > 0 ? '+' : '') + v.toFixed(digits) + '%';
};
const PLACEHOLDER = 'data:image/svg+xml;utf8,' + encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="56"><rect width="40" height="56" rx="8" fill="#F5F5F7"/><text x="20" y="32" font-size="9" fill="#9B98B0" text-anchor="middle" font-family="sans-serif">card</text></svg>'
);
function imgFallback(node) { node.onerror = null; node.src = PLACEHOLDER; }

/* "Prices refreshed" freshness from meta.built_at (last fetch+build). */
function refreshInfo(builtAt) {
  if (!builtAt) return { label: '—', sub: 'unknown', days: null };
  const days = Math.floor((Date.now() - new Date(builtAt).getTime()) / 86400000);
  const date = builtAt.slice(0, 10);
  const label = days <= 0 ? 'Today' : days === 1 ? 'Yesterday' : `${days} days ago`;
  const sub = days >= 3 ? `as of ${date} · refresh recommended` : `as of ${date}`;
  return { label, sub, days };
}

/* Per-set "sealed heat" line from the manual TCGplayer feed (pack momentum +
   today's velocity vs supply). Price up = green (bullish), down = red. */
function sealedLine(sealed) {
  const p = sealed && sealed.pack;
  if (!p) return null;
  const ch = p.change_24h ?? 0;
  const up = ch >= 0;
  const col = up ? 'var(--success-accent)' : 'var(--brand-red-dark)';
  const listed = p.listings == null ? '—'
    : p.listings >= 1000 ? (p.listings / 1000).toFixed(1) + 'k' : String(p.listings);
  return el('div', { class: 'lb-sub', html:
    `📦 ${USD(p.price)} <span style="color:${col};font-weight:600">${up ? '▲' : '▼'} ${Math.abs(ch).toFixed(1)}%</span>` +
    ` · ${(p.sold_today ?? 0).toLocaleString()} sold · ${listed} listed <span style="opacity:.55">24h</span>` });
}

/* residual_pct convention (from real data):
     residual_pct < 0  -> market below expected -> UNDERVALUED (green / down pill)
     residual_pct > 0  -> market above expected -> OVERVALUED  (red / up pill)        */
function deltaPill(residual) {
  if (residual == null) return el('span', { class: 'delta delta--flat', text: '—' });
  const under = residual < 0;
  const cls = under ? 'delta delta--down' : 'delta delta--up';
  return el('span', { class: cls, text: signedPct(residual) });
}
function iqChip(iq) {
  return el('span', { class: 'chip chip--iq', html: `IQ&nbsp;${iq != null ? iq.toFixed(0) : '—'}` });
}

/* ---------- global state ---------- */
const STATE = {
  cards: null, sets: null, leaderboard: null, model: null, meta: null,
  backtest: null, byId: new Map(), loaded: false, error: null,
};

async function loadData() {
  const files = ['cards', 'sets', 'leaderboard', 'model', 'meta'];
  const results = await Promise.all(files.map(async (f) => {
    const res = await fetch(`./data/${f}.json`, { cache: 'no-cache' });
    if (!res.ok) throw new Error(`Failed to load ${f}.json (HTTP ${res.status})`);
    return res.json();
  }));
  [STATE.cards, STATE.sets, STATE.leaderboard, STATE.model, STATE.meta] = results;
  STATE.byId = new Map(STATE.cards.map((c) => [c.id, c]));
  /* backtest.json is optional — never block boot if it's absent */
  try {
    const r = await fetch('./data/backtest.json', { cache: 'no-cache' });
    if (r.ok) STATE.backtest = await r.json();
  } catch (_) { /* no track record yet */ }
  STATE.loaded = true;
}

/* ============================================================
   Live price model — recompute expected price client-side
   expected = exp(intercept + Σ coef_i * ((x_i - mean_i)/std_i))
   ============================================================ */
function modelForCluster(clusterName) {
  const m = STATE.model;
  if (clusterName && m.clusters && m.clusters[clusterName]) return m.clusters[clusterName];
  return m.global;
}
function computeExpected(clusterModel, featureValues) {
  let z = clusterModel.intercept;
  clusterModel.features.forEach((f, i) => {
    const std = clusterModel.stds[i];
    const x = featureValues[f];
    if (std === 0 || x == null || Number.isNaN(x)) return;
    z += clusterModel.coef[i] * ((x - clusterModel.means[i]) / std);
  });
  return Math.exp(z);
}

/* ============================================================
   View renderers
   ============================================================ */
const viewRoot = () => $('#view');

function setView(nodes) {
  const root = viewRoot();
  root.innerHTML = '';
  [].concat(nodes).forEach((n) => n && root.appendChild(n));
  window.scrollTo({ top: 0, behavior: 'auto' });
}

/* ---- shared: leaderboard table ---- */
function leaderboardTable(rows, opts = {}) {
  const head = el('thead', {}, el('tr', {}, [
    el('th', { class: 'lb-rank', text: '#' }),
    el('th', { text: 'Card' }),
    el('th', { class: 'num', text: 'Market' }),
    el('th', { class: 'num', text: 'Expected' }),
    el('th', { class: 'num', text: opts.deltaLabel || 'Signal' }),
    el('th', { class: 'num', text: 'IQ' }),
  ]));
  const body = el('tbody', {}, rows.map((r, i) => {
    const thumb = el('img', { class: 'lb-thumb', src: r.image_small || PLACEHOLDER, alt: r.name, loading: 'lazy' });
    thumb.addEventListener('error', () => imgFallback(thumb));
    const tr = el('tr', { class: 'clickable', dataset: { id: r.id } }, [
      el('td', { class: 'lb-rank num', text: String(i + 1) }),
      el('td', {}, el('div', { class: 'lb-card-cell' }, [
        thumb,
        el('div', {}, [
          el('div', { class: 'lb-name', text: r.name }),
          el('div', { class: 'lb-sub', text: `${r.set_name} · #${r.number} · ${r.rarity}` }),
        ]),
      ])),
      el('td', { class: 'num lb-price', text: USD(r.market_price) }),
      el('td', { class: 'num lb-price lb-price-exp', text: USD(r.expected_price) }),
      el('td', { class: 'num' }, deltaPill(r.residual_pct)),
      el('td', { class: 'num' }, iqChip(r.iq_score)),
    ]);
    tr.addEventListener('click', () => openModal(r.id));
    return tr;
  }));
  return el('div', { class: 'table-card' },
    el('div', { class: 'table-scroll' }, el('table', { class: 'lb' }, [head, body])));
}

/* ============================================================
   1. LANDING / HERO
   ============================================================ */
function viewHome() {
  const meta = STATE.meta;
  const lb = STATE.leaderboard;

  /* hero */
  const heroCardRows = lb.undervalued.slice(0, 3).map((r) => {
    const img = el('img', { src: r.image_small || PLACEHOLDER, alt: r.name, loading: 'lazy' });
    img.addEventListener('error', () => imgFallback(img));
    const row = el('div', { class: 'hero-card-row' }, [
      img,
      el('div', { class: 'hcr-main' }, [
        el('div', { class: 'hcr-name', text: r.name }),
        el('div', { class: 'hcr-set', text: r.set_name }),
      ]),
      deltaPill(r.residual_pct),
    ]);
    row.style.cursor = 'pointer';
    row.addEventListener('click', () => openModal(r.id));
    return row;
  });

  const hero = el('section', { class: 'hero container' },
    el('div', { class: 'hero-grid' }, [
      el('div', {}, [
        el('span', { class: 'chip chip--lavender hero-eyebrow', html: `Beta · ${meta.priced.toLocaleString()} priced cards` }),
        el('h1', { class: 'hero-display' }, [
          'The price lab for ',
          el('span', { class: 'accent', text: 'Pokémon' }),
          ' cards.',
        ]),
        el('p', { class: 'subtitle hero-sub', text:
          'A clustered price model estimates what every card should cost, flags the under- and over-valued, and ranks sealed product by expected value — all from free pokemontcg.io data.' }),
        el('div', { class: 'hero-actions' }, [
          el('a', { class: 'button button-primary', href: '#/pricelab', text: 'Explore the Price Lab' }),
          el('a', { class: 'button button-secondary', href: '#/sets', text: 'See sealed EV →' }),
        ]),
      ]),
      el('div', { class: 'hero-card' }, [
        el('div', { class: 'hero-card-title' }, [
          el('span', { class: 'caption-bold', text: 'Most undervalued right now' }),
          el('span', { class: 'chip chip--teal', text: 'live model' }),
        ]),
        el('div', { class: 'hero-card-rows' }, heroCardRows),
      ]),
    ]));

  /* pastel stat cards from meta.json */
  const fresh = refreshInfo(meta.built_at);
  const statRow = el('div', { class: 'stat-row container' }, [
    statCard('bg-yellow', 'Tracked', meta.cards.toLocaleString(), 'cards in the corpus'),
    statCard('bg-teal', 'Coverage', String(meta.sets), 'Scarlet & Violet sets'),
    statCard('bg-coral', 'Prices refreshed', fresh.label, fresh.sub),
  ]);

  /* how it works */
  const explain = el('section', { class: 'section container' }, [
    el('div', { class: 'section-head' }, [
      el('div', {}, [
        el('p', { class: 'micro section-eyebrow', text: 'How it works' }),
        el('h2', { class: 'h2', text: 'Three signals, one honest model' }),
        el('p', { class: 'section-sub', text:
          'Live signals come straight from pokemontcg.io prices and set composition. Feed-dependent signals are clearly stubbed until their data source is wired.' }),
      ]),
    ]),
    el('div', { class: 'explainer-row' }, [
      explainerCard('bg-yellow', '◎', 'Sealed EV', 'Per-card pull rates × market prices roll up to an expected value per pack and per Elite Trainer Box, versus what each actually costs.'),
      explainerCard('bg-teal', '◈', 'Fair-price model', 'A ridge regression per rarity cluster predicts log price from scarcity, character premium and in-set rank — recomputed live as you move sliders.'),
      explainerCard('bg-coral', '◇', 'Honest stubs', 'Demand pressure, grading intensity and supply saturation need eBay / PSA feeds we don’t have yet, so they’re labeled "awaiting data".'),
    ]),
  ]);

  /* quick links into views */
  const links = el('section', { class: 'section section--tight container' },
    el('div', { class: 'explainer-row' }, [
      quickLink('#/sets', 'bg-lavender', 'Sets / Market Trends', 'Sealed EV leaderboard — best bang for the buck.'),
      quickLink('#/pricelab', 'bg-rose', 'Price Lab', 'Undervalued & overvalued cards with live deltas.'),
      quickLink('#/search', 'bg-teal', 'Search', `Filter all ${meta.cards.toLocaleString()} cards by name or set.`),
    ]));

  setView([hero, statRow, explain, links]);
  highlightNav(null);
}
function statCard(bg, kicker, big, label) {
  return el('div', { class: `stat-card ${bg}` }, [
    el('div', { class: 'stat-kicker', text: kicker }),
    el('div', { class: 'stat-display', text: big }),
    el('div', { class: 'stat-label', text: label }),
  ]);
}
function explainerCard(bg, icon, title, body) {
  return el('div', { class: 'explainer-card' }, [
    el('div', { class: `explainer-icon ${bg}`, text: icon }),
    el('h4', { class: 'h4', text: title }),
    el('p', { text: body }),
  ]);
}
function quickLink(href, bg, title, body) {
  return el('a', { class: `explainer-card`, href }, [
    el('div', { class: `explainer-icon ${bg}`, text: '→' }),
    el('h4', { class: 'h4', text: title }),
    el('p', { text: body }),
  ]);
}

/* ============================================================
   2. SETS / MARKET TRENDS — EV leaderboard
   ============================================================ */
function viewSets() {
  const sets = STATE.sets.slice().sort((a, b) => b.signal_pct - a.signal_pct);

  const head = el('thead', {}, el('tr', {}, [
    el('th', { class: 'lb-rank', text: '#' }),
    el('th', { text: 'Set' }),
    el('th', { class: 'num', text: 'Pack' }),
    el('th', { class: 'num', text: 'EV / pack' }),
    el('th', { class: 'num', text: 'Pack verdict' }),
    el('th', { class: 'num', text: 'ETB' }),
    el('th', { class: 'num', text: 'EV / ETB' }),
    el('th', { class: 'num', text: 'ETB verdict' }),
  ]));
  const body = el('tbody', {}, sets.map((s, i) => {
    const logo = el('img', { class: 'lb-logo', src: s.logo || PLACEHOLDER, alt: s.name, loading: 'lazy' });
    logo.addEventListener('error', () => imgFallback(logo));
    return el('tr', {}, [
      el('td', { class: 'lb-rank num', text: String(i + 1) }),
      el('td', {}, el('div', { class: 'lb-set-cell' }, [
        logo,
        el('div', {}, [
          el('div', { class: 'lb-name', text: s.name }),
          el('div', { class: 'lb-sub', text: `${s.series} · ${s.packs_per_etb} packs/ETB` }),
          sealedLine(s.sealed),
        ]),
      ])),
      el('td', { class: 'num lb-price', text: USD(s.pack_price) }),
      el('td', { class: 'num lb-price', text: USD(s.ev_per_pack) }),
      el('td', { class: 'num' }, evSignalPill(s.pack_signal_pct)),
      el('td', { class: 'num lb-price', text: USD0(s.etb_price) }),
      el('td', { class: 'num lb-price', text: USD0(s.ev_per_etb) }),
      el('td', { class: 'num' }, evSignalPill(s.etb_signal_pct)),
    ]);
  }));
  const table = el('div', { class: 'table-card' },
    el('div', { class: 'table-scroll' }, el('table', { class: 'lb' }, [head, body])));

  const section = el('section', { class: 'section container' }, [
    el('div', { class: 'section-head' }, [
      el('div', {}, [
        el('p', { class: 'micro section-eyebrow', text: 'Sets · Market Trends' }),
        el('h2', { class: 'h2', text: 'Undervalued & overvalued sets' }),
        el('p', { class: 'section-sub', text:
          'Sealed expected value = Σ (per-card pull rate × market price), shown per single pack and per Elite Trainer Box (9 packs), each vs what that product costs. Green “Undervalued” = the cards inside are worth more than the sealed product (good to rip / hold); red “Overvalued” = you pay a premium for sealed (buy singles). A value signal, not a price-trend forecast.' }),
      ]),
      el('span', { class: 'chip chip--teal', text: 'live · pokemontcg.io' }),
    ]),
    table,
    el('p', { class: 'caption', html: 'Pull rates are sourced from large community / TCGplayer-style samples (SIR &amp; Hyper Rare per set). Pack &amp; ETB prices are TCGplayer-sourced estimates — Paldean Fates and Shrouded Fable ETB prices are lower-confidence.' }),
  ]);

  setView(section);
  highlightNav('sets');
}
function evSignalPill(pct) {
  /* positive signal_pct = sealed box cheaper than the cards inside = undervalued (green);
     negative = paying a premium for sealed = overvalued (red) */
  if (pct == null) return el('span', { class: 'delta delta--flat', text: '—' });
  const verdict = pct >= 0.10 ? 'Undervalued' : pct <= -0.10 ? 'Overvalued' : 'Fair';
  const cls = pct >= 0.10 ? 'delta delta--down' : pct <= -0.10 ? 'delta delta--up' : 'delta delta--flat';
  return el('span', { class: cls, text: `${verdict} ${signedPct(pct, 0)}` });
}

/* ============================================================
   3. PRICE LAB — undervalued + overvalued
   ============================================================ */
function viewPriceLab() {
  const lb = STATE.leaderboard;

  const under = el('div', {}, [
    el('div', { class: 'lab-col-head' }, [
      el('span', { class: 'chip chip--teal', text: 'Undervalued' }),
      el('h3', { class: 'h3', text: 'Market below model' }),
    ]),
    leaderboardTable(lb.undervalued, { deltaLabel: 'Discount' }),
  ]);
  const over = el('div', {}, [
    el('div', { class: 'lab-col-head' }, [
      el('span', { class: 'chip', style: 'background:var(--brand-red);color:var(--brand-red-dark)', text: 'Overvalued' }),
      el('h3', { class: 'h3', text: 'Market above model' }),
    ]),
    leaderboardTable(lb.overvalued, { deltaLabel: 'Premium' }),
  ]);

  const section = el('section', { class: 'section container' }, [
    el('div', { class: 'section-head' }, [
      el('div', {}, [
        el('p', { class: 'micro section-eyebrow', text: 'Price Lab' }),
        el('h2', { class: 'h2', text: 'Undervalued & overvalued cards' }),
        el('p', { class: 'section-sub', text:
          'The model predicts a fair price for each card from scarcity, character premium and in-set rank. The delta is how far the live market sits from that estimate. Open any card to tune the signals yourself.' }),
      ]),
      el('span', { class: 'chip chip--lavender', html: `R²&nbsp;${(STATE.meta.model_r2_log ?? 0).toFixed(2)} · ${STATE.meta.clusters} clusters` }),
    ]),
    el('div', { class: 'lab-grid' }, [under, over]),
    el('p', { class: 'caption', html: 'Expected price is a statistical <strong>estimate</strong>, not an appraisal. Green = trading below the model (potential value); red = trading above (potential premium).' }),
  ]);

  setView(section);
  highlightNav('pricelab');
}

/* ============================================================
   4. MOVERS — saturation-shift when live, price-fallback stub otherwise
   ============================================================ */
const isSaturationBasis = (basis) => basis === 'saturation_shift';

/* supply-saturation tag: <1 tightening (green), >1 loosening (red), ~1 steady */
function saturationTag(sat) {
  if (sat == null) return el('span', { class: 'delta delta--flat', text: '—' });
  const shiftPct = Math.abs(sat - 1) * 100;
  if (sat < 0.97) return el('span', { class: 'delta delta--down', text: `tightening −${shiftPct.toFixed(0)}%` });
  if (sat > 1.03) return el('span', { class: 'delta delta--up', text: `loosening +${shiftPct.toFixed(0)}%` });
  return el('span', { class: 'delta delta--flat', text: 'steady' });
}

/* live movers table: rank by |saturation−1|, show tag + active listings + 7d sold */
function moversTableLive(rows) {
  const head = el('thead', {}, el('tr', {}, [
    el('th', { class: 'lb-rank', text: '#' }),
    el('th', { text: 'Card' }),
    el('th', { class: 'num', text: 'Saturation' }),
    el('th', { class: 'num', text: 'Supply shift' }),
    el('th', { class: 'num', text: 'Active' }),
    el('th', { class: 'num', text: 'Sold 7d' }),
  ]));
  const body = el('tbody', {}, rows.map((r, i) => {
    const dyn = r.dynamics || {};
    const awaiting = dyn.status === 'awaiting_data';
    const sat = dyn.supply_saturation;
    const thumb = el('img', { class: 'lb-thumb', src: r.image_small || PLACEHOLDER, alt: r.name, loading: 'lazy' });
    thumb.addEventListener('error', () => imgFallback(thumb));
    const tr = el('tr', { class: 'clickable', dataset: { id: r.id } }, [
      el('td', { class: 'lb-rank num', text: String(i + 1) }),
      el('td', {}, el('div', { class: 'lb-card-cell' }, [
        thumb,
        el('div', {}, [
          el('div', { class: 'lb-name', text: r.name }),
          el('div', { class: 'lb-sub', text: `${r.set_name} · #${r.number} · ${r.rarity}` }),
        ]),
      ])),
      el('td', { class: 'num lb-price', text: awaiting ? '—' : `${Number(sat).toFixed(2)}×` }),
      el('td', { class: 'num' }, awaiting ? el('span', { class: 'badge-stub', text: 'awaiting data' }) : saturationTag(sat)),
      el('td', { class: 'num lb-price', text: awaiting || dyn.active_listings == null ? '—' : dyn.active_listings.toLocaleString() }),
      el('td', { class: 'num lb-price', text: awaiting || dyn.sold_7d == null ? '—' : dyn.sold_7d.toLocaleString() }),
    ]);
    tr.addEventListener('click', () => openModal(r.id));
    return tr;
  }));
  return el('div', { class: 'table-card' },
    el('div', { class: 'table-scroll' }, el('table', { class: 'lb' }, [head, body])));
}

function viewMovers() {
  const lb = STATE.leaderboard;
  const live = isSaturationBasis(lb.movers_basis);

  const banner = live
    ? el('div', { class: 'table-card', style: 'padding:20px 24px;display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin-bottom:24px;box-shadow:none;background:var(--surface-soft)' }, [
        el('span', { class: 'chip chip--teal', text: 'live · eBay supply' }),
        el('p', { class: 'body-sm', style: 'margin:0;color:var(--slate);max-width:64ch', html:
          'Ranked by <strong>supply-saturation shift</strong> = mean active listings over the last 7 days vs the last 30 days. <span style="color:var(--success-accent);font-weight:600">Tightening</span> (below 1×) means supply is drying up faster than it’s replenishing; <span style="color:var(--brand-red-dark);font-weight:600">loosening</span> (above 1×) means listings are piling up. Sold figures are estimated by diffing daily active-listing snapshots.' }),
      ])
    : el('div', { class: 'table-card', style: 'padding:20px 24px;display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin-bottom:24px;box-shadow:none;background:var(--surface-soft)' }, [
        el('span', { class: 'badge-stub', text: 'awaiting eBay data' }),
        el('p', { class: 'body-sm', style: 'margin:0;color:var(--slate);max-width:62ch', html:
          'Real day-over-day movers need the <strong>eBay Browse API</strong> (active-listing snapshots, diffed daily to estimate sold/unsold) — which isn’t wired yet. Until then we fall back to the cards whose market price diverges most from the model.' }),
      ]);

  const section = el('section', { class: 'section container' }, [
    el('div', { class: 'section-head' }, [
      el('div', {}, [
        el('p', { class: 'micro section-eyebrow', text: 'Movers' }),
        el('h2', { class: 'h2', text: 'Biggest market movers' }),
        el('p', { class: 'section-sub', text: live
          ? 'Ranked by 7-day vs 30-day listing-supply shift. Tightening supply (green) tends to precede price strength; loosening supply (red) tends to precede softening.'
          : 'When supply data lands, this ranks cards by 7-day vs 30-day listing-supply shift (loosening vs tightening). For now it shows the largest price-vs-model gaps as a placeholder basis.' }),
      ]),
      live ? el('span', { class: 'chip chip--teal', text: 'live' }) : el('span', { class: 'badge-stub', text: 'stub · price fallback' }),
    ]),
    banner,
    live ? moversTableLive(lb.movers) : leaderboardTable(lb.movers, { deltaLabel: 'Price gap' }),
    el('p', { class: 'caption', html: live
      ? 'Basis: <code>saturation_shift</code> — mean active listings (7d) ÷ mean active listings (30d), inferred from daily eBay active-listing snapshots. Sold/unsold are estimated by day-over-day diffing, not confirmed sold comps.'
      : `Basis: <code>${lb.movers_basis || 'price_signal_fallback'}</code> — a stand-in until supply-saturation data exists. No eBay / sold-comp feed is implied.` }),
  ]);

  setView(section);
  highlightNav('movers');
}

/* ============================================================
   5. SEARCH — filter all cards
   ============================================================ */
let searchTimer = null;
function viewSearch() {
  const setNames = Array.from(new Set(STATE.cards.map((c) => c.set_name))).sort();

  const input = el('input', { class: 'search-input', type: 'search', placeholder: 'Search by card name…', 'aria-label': 'Search cards' });
  const setSelect = el('select', { class: 'search-select', 'aria-label': 'Filter by set' }, [
    el('option', { value: '', text: 'All sets' }),
    ...setNames.map((s) => el('option', { value: s, text: s })),
  ]);
  const sortSelect = el('select', { class: 'search-select', 'aria-label': 'Sort' }, [
    el('option', { value: 'price-desc', text: 'Price: high → low' }),
    el('option', { value: 'price-asc', text: 'Price: low → high' }),
    el('option', { value: 'iq-desc', text: 'IQ: high → low' }),
    el('option', { value: 'under', text: 'Most undervalued' }),
    el('option', { value: 'over', text: 'Most overvalued' }),
    el('option', { value: 'name', text: 'Name A → Z' }),
  ]);

  const count = el('div', { class: 'search-count' });
  const grid = el('div', { class: 'card-grid' });

  function render() {
    const q = input.value.trim().toLowerCase();
    const setFilter = setSelect.value;
    const sort = sortSelect.value;

    let rows = STATE.cards.filter((c) => {
      if (setFilter && c.set_name !== setFilter) return false;
      if (!q) return true;
      return c.name.toLowerCase().includes(q) || (c.set_name || '').toLowerCase().includes(q) || (c.number || '').toLowerCase().includes(q);
    });

    const priceOf = (c) => (c.market_price == null ? -1 : c.market_price);
    rows.sort((a, b) => {
      switch (sort) {
        case 'price-asc': return priceOf(a) - priceOf(b);
        case 'iq-desc': return (b.iq_score ?? 0) - (a.iq_score ?? 0);
        case 'under': return (a.residual_pct ?? 0) - (b.residual_pct ?? 0);
        case 'over': return (b.residual_pct ?? 0) - (a.residual_pct ?? 0);
        case 'name': return a.name.localeCompare(b.name);
        case 'price-desc':
        default: return priceOf(b) - priceOf(a);
      }
    });

    const total = rows.length;
    const shown = rows.slice(0, 120);
    count.textContent = `${total.toLocaleString()} card${total === 1 ? '' : 's'}${total > shown.length ? ` (showing first ${shown.length})` : ''}`;

    grid.innerHTML = '';
    if (!shown.length) {
      grid.appendChild(el('div', { class: 'state' }, [
        el('div', { class: 'h3', text: 'No cards match' }),
        el('p', { text: 'Try a different name or clear the set filter.' }),
      ]));
      return;
    }
    const frag = document.createDocumentFragment();
    shown.forEach((c) => frag.appendChild(miniCard(c)));
    grid.appendChild(frag);
  }

  input.addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(render, 120); });
  setSelect.addEventListener('change', render);
  sortSelect.addEventListener('change', render);

  const section = el('section', { class: 'section container' }, [
    el('div', { class: 'section-head' }, [
      el('div', {}, [
        el('p', { class: 'micro section-eyebrow', text: 'Search' }),
        el('h2', { class: 'h2', text: 'Browse every card' }),
        el('p', { class: 'section-sub', text: `All ${STATE.cards.length.toLocaleString()} cards in the corpus, each with its market price, model price and IQ score. Click any card for the full signal panel.` }),
      ]),
    ]),
    el('div', { class: 'search-bar' }, [input, setSelect, sortSelect]),
    count,
    grid,
  ]);

  setView(section);
  highlightNav('search');
  render();
  input.focus();
}

function miniCard(c) {
  const img = el('img', { src: c.image_small || PLACEHOLDER, alt: c.name, loading: 'lazy' });
  img.addEventListener('error', () => imgFallback(img));
  const node = el('div', { class: 'mini-card', dataset: { id: c.id } }, [
    el('div', { class: 'mini-card-img' }, img),
    el('div', {}, [
      el('div', { class: 'mini-card-name', text: c.name }),
      el('div', { class: 'mini-card-sub', text: `${c.set_name} · #${c.number}` }),
    ]),
    el('div', { class: 'mini-card-foot' }, [
      el('span', { class: 'lb-price', text: USD(c.market_price) }),
      deltaPill(c.residual_pct),
    ]),
  ]);
  node.addEventListener('click', () => openModal(c.id));
  return node;
}

/* ============================================================
   CARD-DETAIL MODAL + live signals panel
   ============================================================ */
let lastFocused = null;

function openModal(id) {
  const card = STATE.byId.get(id);
  if (!card) return;
  lastFocused = document.activeElement;

  const backdrop = $('#modalBackdrop');
  const modal = $('#modal');
  modal.innerHTML = '';
  modal.appendChild(buildModalContent(card));
  backdrop.hidden = false;
  document.body.style.overflow = 'hidden';
  if (location.hash.indexOf('card=') === -1) {
    history.replaceState(null, '', `${location.hash || '#/pricelab'}${location.hash.includes('?') ? '&' : '?'}card=${encodeURIComponent(id)}`);
  }
  const closeBtn = $('.modal-close', modal);
  if (closeBtn) closeBtn.focus();
}

function closeModal() {
  const backdrop = $('#modalBackdrop');
  backdrop.hidden = true;
  $('#modal').innerHTML = '';
  document.body.style.overflow = '';
  if (location.hash.includes('card=')) {
    history.replaceState(null, '', location.hash.replace(/[?&]card=[^&]*/,''));
  }
  if (lastFocused && lastFocused.focus) lastFocused.focus();
}

function buildModalContent(card) {
  const clusterModel = modelForCluster(card.cluster);
  const featMeta = STATE.model.feature_meta;

  /* working copy of feature values (start at the card's real features) */
  const working = {};
  clusterModel.features.forEach((f) => { working[f] = card.features[f]; });

  /* image */
  const bigImg = el('img', { src: card.image_large || card.image_small || PLACEHOLDER, alt: card.name, loading: 'lazy' });
  bigImg.addEventListener('error', () => imgFallback(bigImg));

  /* big delta */
  const under = (card.residual_pct ?? 0) < 0;
  const deltaBig = el('div', { class: 'price-delta-big' }, [
    el('div', { class: `pd-num ${under ? 'pd-down' : 'pd-up'}`, text: signedPct(card.residual_pct) }),
    el('div', { class: `pd-label ${under ? 'pd-down' : 'pd-up'}`, text: under ? 'undervalued' : 'overvalued' }),
  ]);

  const priceBlock = el('div', { class: 'price-block' }, [
    el('div', { class: 'price-cell' }, [
      el('div', { class: 'price-label', text: 'Market' }),
      el('div', { class: 'price-value', text: USD(card.market_price) }),
    ]),
    el('div', { class: 'price-cell' }, [
      el('div', { class: 'price-label', text: 'Model (expected)' }),
      el('div', { class: 'price-value expected', text: USD(card.expected_price) }),
    ]),
    deltaBig,
  ]);

  /* gauges: demand pressure + supply saturation from card.dynamics */
  const dyn = card.dynamics || {};
  const dynLive = dyn.status === 'ok' && dyn.demand_pressure != null;
  const gauges = el('div', { class: 'gauges' }, [
    demandGauge(dyn, !dynLive),
    saturationGauge(dyn, dyn.status === 'awaiting_data'),
  ]);

  /* ----- live signals panel ----- */
  const livePriceVal = el('span', { class: 'slp-val', text: USD(card.expected_price) });
  const livePriceDelta = el('span', { class: 'slp-delta', text: signedPct(card.residual_pct) });

  function recompute() {
    const expected = computeExpected(clusterModel, working);
    livePriceVal.textContent = USD(expected);
    if (card.market_price != null && expected > 0) {
      const resid = (card.market_price - expected) / expected;
      const u = resid < 0;
      livePriceDelta.textContent = signedPct(resid) + (u ? ' undervalued' : ' overvalued');
      livePriceDelta.style.color = u ? 'var(--success-accent)' : 'var(--brand-red-dark)';
    } else {
      livePriceDelta.textContent = 'no market price';
      livePriceDelta.style.color = 'var(--steel)';
    }
  }

  const sliderRows = clusterModel.features.map((f, i) => {
    const meta = featMeta[f] || { label: f, min: 0, max: 10, status: 'live' };
    const isStub = meta.status === 'stub';
    const std = clusterModel.stds[i];
    const inert = std === 0; /* feature with zero variance in this cluster: no price effect */
    const step = (meta.max - meta.min) / 200 || 0.01;
    const val0 = working[f] != null ? working[f] : (meta.min + meta.max) / 2;

    const valOut = el('span', { class: 'slider-val', text: fmtFeat(f, val0) });
    const contribOut = el('div', { class: 'slider-contrib' });
    const slider = el('input', {
      class: `sig-slider${isStub ? ' is-stub' : ''}`, type: 'range',
      min: meta.min, max: meta.max, step, value: val0,
      'aria-label': meta.label,
    });

    function updateContrib() {
      if (inert) { contribOut.textContent = 'No price effect in this cluster (flat in the model).'; return; }
      const z = clusterModel.coef[i] * ((working[f] - clusterModel.means[i]) / std);
      const dir = z > 0.0005 ? '▲ raises' : (z < -0.0005 ? '▼ lowers' : '· neutral');
      contribOut.textContent = `${dir} the estimate (contribution ${z >= 0 ? '+' : ''}${z.toFixed(3)} in log-price)`;
    }

    slider.addEventListener('input', () => {
      working[f] = parseFloat(slider.value);
      valOut.textContent = fmtFeat(f, working[f]);
      updateContrib();
      recompute();
    });
    updateContrib();

    const nameEl = el('span', { class: 'slider-name' }, [
      meta.label,
      isStub ? el('span', { class: 'badge-stub', text: 'awaiting data' }) : null,
      inert && !isStub ? el('span', { class: 'chip', text: 'no effect' }) : null,
    ]);

    return { node: el('div', { class: 'slider-row' }, [
      el('div', { class: 'slider-top' }, [nameEl, valOut]),
      slider, contribOut,
    ]), reset: () => { working[f] = card.features[f]; slider.value = val0; valOut.textContent = fmtFeat(f, val0); updateContrib(); } };
  });

  const resetBtn = el('button', { class: 'button button-secondary button-sm', text: 'Reset to model values' });
  resetBtn.addEventListener('click', () => { sliderRows.forEach((r) => r.reset()); recompute(); });

  const signalsPanel = el('div', { class: 'signals-panel' }, [
    el('div', { class: 'signals-head' }, [
      el('h4', { class: 'h4', text: 'View Market Signals' }),
      el('span', { class: 'chip chip--lavender', html: `cluster · ${card.cluster}` }),
    ]),
    el('p', { class: 'signals-note', html:
      'Each slider is a model input. Moving one recomputes the expected price live, client-side, from this cluster’s exported coefficients: <code>expected = exp(intercept + Σ coef·z)</code>. Stubbed signals are labeled and currently carry zero weight.' }),
    el('div', { class: 'signals-live-price' }, [
      el('span', { class: 'slp-label', text: 'Live expected price' }),
      livePriceVal,
      livePriceDelta,
    ]),
    ...sliderRows.map((r) => r.node),
    el('div', { class: 'signals-foot' }, [
      el('span', { class: 'caption', text: 'Estimate only — not an appraisal or offer.' }),
      resetBtn,
    ]),
  ]);

  /* ----- assemble ----- */
  const closeBtn = el('button', { class: 'modal-close', 'aria-label': 'Close', text: '✕' });
  closeBtn.addEventListener('click', closeModal);

  return el('div', {}, [
    closeBtn,
    el('div', { class: 'modal-grid' }, [
      el('div', { class: 'modal-img-wrap' }, bigImg),
      el('div', { class: 'modal-body' }, [
        el('div', { class: 'modal-eyebrow' }, [
          el('span', { class: 'chip', text: card.rarity }),
          el('span', { class: 'chip', text: `#${card.number}` }),
          card.price_variant ? el('span', { class: 'chip chip--yellow', text: card.price_variant }) : null,
        ]),
        el('h3', { class: 'h2 modal-title', text: card.name }),
        el('div', { class: 'modal-setline', text: `${card.set_name} · ${card.series} · ${card.release_date}` }),
        priceBlock,
        (card.features && card.features.pull_cost)
          ? el('p', { class: 'caption', html:
              `<strong>Cost to pull one ≈ ${USD0(card.features.pull_cost)}</strong> — expected spend on booster packs (at today's market pack price) to hit this exact card once. Buying the single at ${USD(card.market_price)} is ${card.features.pull_cost > (card.market_price || 0) ? 'far cheaper' : 'pricier'} than chasing it.` })
          : null,
        el('div', { class: 'iq-row' }, [
          el('span', { class: 'iq-badge' }, [
            el('span', { class: 'iq-num', text: card.iq_score != null ? card.iq_score.toFixed(0) : '—' }),
            el('span', { class: 'iq-of', text: '/ 100 IQ' }),
          ]),
          el('span', { class: 'caption', text: 'composite of scarcity, character premium & in-set rank' }),
        ]),
        gauges,
        el('p', { class: 'caption', html: dynLive
          ? `Demand pressure = est. sold (7d) ÷ total supply; supply saturation = active listings 7-day vs 30-day average. Inferred from daily eBay active-listing snapshots${dyn.active_listings != null ? ` (${dyn.active_listings.toLocaleString()} active, ${(dyn.sold_7d ?? 0).toLocaleString()} est. sold this week)` : ''}.`
          : 'Demand pressure & supply saturation need an eBay feed — shown as <strong>awaiting data</strong>.' }),
        signalsPanel,
      ]),
    ]),
  ]);
}

/* shared gauge shell */
function gaugeShell(label, badge, barChildren, readout) {
  return el('div', { class: 'gauge' }, [
    el('div', { class: 'gauge-head' }, [
      el('span', { class: 'gauge-label', text: label }),
      badge,
    ]),
    el('div', { class: 'gauge-bar' }, barChildren),
    el('div', { class: 'gauge-value', text: readout }),
  ]);
}

/* Demand pressure: est_sold(7d)/total_supply as a %. Coral→yellow→red fill by magnitude.
   The gradient bar is full-width and a mask reveals it up to the value, so low % reads
   coral and high % climbs into red. Scaled so ~40%+ pressure pegs the gauge. */
function demandGauge(dyn, isStub) {
  const DP_FULL = 0.40; /* demand_pressure that fills the gauge */
  if (isStub) {
    const fill = el('div', { class: 'gauge-fill is-stub', style: 'width:100%' });
    return gaugeShell('Demand pressure',
      el('span', { class: 'badge-stub', text: 'stub' }), fill, 'awaiting data');
  }
  const dp = dyn.demand_pressure;
  const frac = Math.max(0, Math.min(1, dp / DP_FULL));
  const fill = el('div', { class: 'gauge-fill', style: `width:${(frac * 100).toFixed(0)}%` });
  return gaugeShell('Demand pressure',
    el('span', { class: 'chip chip--teal', text: 'est' }), fill,
    `${PCT(dp)} of supply sold in 7d (est.)`);
}

/* Supply saturation: a needle centered on 1.0 (steady). Left of center = tightening
   (green), right = loosening (red). Maps saturation in [0.5, 1.5] to needle [0,100%]. */
function saturationGauge(dyn, isStub) {
  if (isStub) {
    const fill = el('div', { class: 'gauge-fill is-stub', style: 'width:100%' });
    return gaugeShell('Supply saturation',
      el('span', { class: 'badge-stub', text: 'stub' }), fill, 'awaiting data');
  }
  const sat = dyn.supply_saturation != null ? dyn.supply_saturation : 1;
  const SPAN = 0.5; /* saturation range shown each side of 1.0 */
  const pos = Math.max(0, Math.min(1, (sat - (1 - SPAN)) / (2 * SPAN))) * 100;
  const tone = sat < 0.97 ? 'tightening' : sat > 1.03 ? 'loosening' : 'steady';
  const needle = el('div', { class: `gauge-needle gauge-needle--${tone}`, style: `left:${pos.toFixed(1)}%` });
  const track = el('div', { class: 'gauge-track gauge-track--saturation' }, [
    el('div', { class: 'gauge-center-mark' }), needle,
  ]);
  const word = sat < 0.97 ? 'tightening' : sat > 1.03 ? 'loosening' : 'steady';
  return gaugeShell('Supply saturation',
    el('span', { class: 'chip chip--teal', text: 'est' }), track,
    `${sat.toFixed(2)}× · ${word} (>1 loosening, <1 tightening)`);
}

function fmtFeat(f, v) {
  if (v == null) return '—';
  if (f === 'pull_cost') return USD0(v);
  if (f === 'set_rank') return v.toFixed(2);
  if (f === 'months_since_release') return `${v.toFixed(0)} mo`;
  return v.toFixed(2);
}

/* ============================================================
   5. TRACK RECORD — backtest of the model vs real TCGplayer history
   ============================================================ */
function trIcColor(ic) {
  if (ic == null) return '#868e96';
  if (ic >= 0.04) return 'var(--success-accent)';
  if (ic <= -0.02) return 'var(--brand-red-dark)';
  return '#868e96';
}
const trIc = (ic) => ic == null ? '—' : (ic >= 0 ? '+' : '') + Number(ic).toFixed(3);
const icCell = (ic) => el('span', { style: 'font-weight:600;color:' + trIcColor(ic), text: trIc(ic) });

function trHeadlineCard(title, c, verdict) {
  const tone = trIcColor(c.ic);
  return el('div', { style: 'flex:1 1 220px;min-width:200px;background:var(--surface,#fff);border:1px solid var(--line,#ECECF1);border-radius:16px;padding:20px;border-top:4px solid ' + tone }, [
    el('div', { class: 'micro', text: title }),
    el('div', { style: 'font-size:40px;font-weight:700;line-height:1.1;margin:6px 0;color:' + tone, text: trIc(c.ic) }),
    el('div', { class: 'caption', text: 'rank IC · 28-day' }),
    el('div', { class: 'micro', style: 'margin-top:8px', text: 'HAC t = ' + (c.nw_t == null ? '—' : c.nw_t) + ' · ' + c.sign_pos + '/' + c.n_dates + ' weeks positive' }),
    el('div', { style: 'margin-top:10px;font-weight:700;color:' + tone, text: verdict }),
    el('p', { class: 'caption', style: 'margin-top:8px', text: c.note || '' }),
  ]);
}

function trMiniTable(caption, headers, rows) {
  const head = el('thead', {}, el('tr', {}, headers.map((hh, i) => el('th', { class: i ? 'num' : '', text: hh }))));
  const body = el('tbody', {}, rows.map((r) => el('tr', {}, r.map((cell, i) =>
    (cell && cell.nodeType) ? el('td', { class: i ? 'num' : '' }, cell)
                            : el('td', { class: i ? 'num' : '', text: String(cell) })))));
  return el('div', {}, [
    caption ? el('p', { class: 'micro section-eyebrow', text: caption }) : null,
    el('div', { class: 'table-card' }, el('div', { class: 'table-scroll' }, el('table', { class: 'lb' }, [head, body]))),
  ]);
}

function trSparkline(series) {
  const max = Math.max(0.3, ...series.map((s) => Math.abs(s.ic)));
  return el('div', { style: 'display:flex;gap:2px;align-items:flex-end;height:48px;overflow-x:auto;padding-top:4px' },
    series.map((s) => el('div', {
      title: s.date + ': IC ' + trIc(s.ic),
      style: 'width:5px;flex:0 0 5px;height:' + Math.max(2, Math.round(Math.abs(s.ic) / max * 44)) + 'px;border-radius:1px;background:' + (s.ic >= 0 ? 'var(--success-accent)' : 'var(--brand-red-dark)'),
    })));
}

function viewTrackRecord() {
  const bt = STATE.backtest;
  if (!bt) {
    setView(el('section', { class: 'section container' }, el('div', { class: 'section-head' }, el('div', {}, [
      el('p', { class: 'micro section-eyebrow', text: 'Track Record' }),
      el('h2', { class: 'h2', text: 'Track record is being prepared' }),
      el('p', { class: 'section-sub', text: 'The backtest appears here after the next data refresh publishes it.' }),
    ]))));
    highlightNav('trackrecord');
    return;
  }
  const p = bt.panel, h = bt.headline, hr = bt.hit_rates || {}, dec = bt.decile || {};

  const heads = el('div', { style: 'display:flex;flex-wrap:wrap;gap:14px;margin-top:6px' }, [
    h.fresh_release ? trHeadlineCard('Fresh releases (≤35 days old)', h.fresh_release, 'Strong & robust') : null,
    h.mature_liquid ? trHeadlineCard('Mature & liquid (>90d, >$10)', h.mature_liquid, '≈ no edge — honest') : null,
    h.all_cards ? trHeadlineCard('All cards ($2+)', h.all_cards, 'Modest') : null,
  ]);

  const freshPct = (h.fresh_release && h.fresh_release.mean_fwd_return != null)
    ? Math.round(Math.abs(h.fresh_release.mean_fwd_return) * 100) + '%' : '~10%';
  const verdict = el('div', { style: 'background:var(--surface-soft,#F7F7FB);border-radius:16px;padding:18px 20px;margin-top:18px' }, [
    el('p', { class: 'h3', style: 'margin:0 0 6px', text: 'What the numbers say' }),
    el('p', { class: 'section-sub', style: 'margin:0', html:
      'The model is genuinely good at <strong>one valuable thing</strong>: spotting freshly-released cards that are overpriced and about to fall. Fresh cards drop about <strong>' + freshPct +
      '</strong> in their first month, and the model reliably ranks which fall hardest. On established, liquid cards it has little measurable edge — treat it as a value gauge, not a crystal ball.' }),
  ]);

  const ageTable = trMiniTable('Edge by card age (since release)',
    ['Age bucket', 'IC', 'Avg 28d return', 'Obs'],
    (bt.by_age_bucket || []).map((r) => [r.bucket, icCell(r.ic), signedPct(r.mean_return, 0), r.n_obs.toLocaleString()]));
  const floorTable = trMiniTable('Edge by price floor',
    ['Min price', 'IC', 'Significance', 'Weeks'],
    (bt.floor_sensitivity || []).map((r) => ['$' + r.floor.toFixed(0) + '+', icCell(r.ic), 'HAC t ' + (r.nw_t == null ? '—' : r.nw_t), r.n_dates]));
  const rarTable = trMiniTable('Edge by rarity',
    ['Rarity', 'IC', 'Avg 28d return', 'Frac up', 'n'],
    (bt.by_rarity || []).map((r) => [r.key, icCell(r.ic), signedPct(r.mean_return, 0), PCT(r.frac_up, 0), r.n.toLocaleString()]));

  const fine = el('p', { class: 'caption', html:
    'Confident calls: undervalued cards rose <strong>' + PCT(hr.under, 0) + '</strong> of the time, overvalued fell <strong>' + PCT(hr.over, 0) +
    '</strong> — vs a ' + PCT(hr.base_up, 0) + ' coin-flip base rate. Most-undervalued decile returned ' + signedPct(dec.top_undervalued_return, 0) +
    ' vs ' + signedPct(dec.bottom_overvalued_return, 0) + ' for the most-overvalued (28-day).' });

  const section = el('section', { class: 'section container' }, [
    el('div', { class: 'section-head' }, [
      el('div', {}, [
        el('p', { class: 'micro section-eyebrow', text: 'Track Record · backtested on real TCGplayer history' }),
        el('h2', { class: 'h2', text: 'Does the model actually work?' }),
        el('p', { class: 'section-sub', text:
          'We replayed the model across ' + p.n_dates + ' weekly snapshots (' + p.first_date + ' → ' + p.last_date +
          '), refitting it with only the prices known on each date, then checked its over/under calls against what prices actually did ' +
          p.primary_horizon_days + ' days later. “Rank IC” measures how well the calls ranked future winners (0 = coin flip).' }),
      ]),
      el('span', { class: 'chip chip--lavender', text: p.n_dates + ' weeks · ' + p.primary_horizon_days + 'd horizon' }),
    ]),
    heads,
    verdict,
    el('div', { class: 'lab-grid', style: 'margin-top:20px' }, [ageTable, floorTable]),
    el('div', { style: 'margin-top:20px' }, rarTable),
    el('div', { style: 'margin-top:20px' }, [
      el('p', { class: 'micro section-eyebrow', text: 'Weekly rank IC (all cards, 28-day) — green = the model ranked that week right' }),
      trSparkline(bt.ic_timeseries || []),
    ]),
    fine,
    el('div', { style: 'margin-top:14px' }, [
      el('p', { class: 'micro section-eyebrow', text: 'Honest caveats' }),
      el('ul', { class: 'caption', style: 'margin:6px 0 0;padding-left:18px' },
        (bt.caveats || []).map((c) => el('li', { text: c }))),
    ]),
    el('p', { class: 'caption', style: 'margin-top:12px', html:
      'Source: daily TCGplayer price history via tcgcsv.com (free, no scraping). Significance uses overlap-corrected (Newey-West) t-stats. This is a backtest of a statistical model, <strong>not</strong> investment advice.' }),
  ]);

  setView(section);
  highlightNav('trackrecord');
}

/* ============================================================
   Router
   ============================================================ */
const ROUTES = {
  '': viewHome,
  '/': viewHome,
  '/sets': viewSets,
  '/pricelab': viewPriceLab,
  '/movers': viewMovers,
  '/trackrecord': viewTrackRecord,
  '/search': viewSearch,
};

function parseHash() {
  let h = location.hash.replace(/^#/, '');
  let cardId = null;
  const qi = h.indexOf('?');
  if (qi !== -1) {
    const params = new URLSearchParams(h.slice(qi + 1));
    cardId = params.get('card');
    h = h.slice(0, qi);
  }
  return { path: h || '/', cardId };
}

function router() {
  if (!STATE.loaded) return;
  const { path, cardId } = parseHash();
  const view = ROUTES[path] || ROUTES[path.replace(/\/$/, '')] || viewHome;
  view();
  if (cardId) openModal(cardId);
  else if (!$('#modalBackdrop').hidden) closeModal();
}

function highlightNav(route) {
  $$('.nav-tab').forEach((t) => t.classList.toggle('is-active', t.dataset.route === route));
  $$('.nav-mobile-link').forEach((t) => t.classList.toggle('is-active', t.dataset.route === route));
}

/* ============================================================
   Boot
   ============================================================ */
function showLoading() {
  setView(el('div', { class: 'state' }, [
    el('div', { class: 'spinner' }),
    el('div', { class: 'h3', text: 'Loading the lab…' }),
    el('p', { text: 'Fetching cards, sets and the price model.' }),
  ]));
}
function showError(err) {
  setView(el('div', { class: 'state' }, [
    el('div', { class: 'h3', text: 'Could not load data' }),
    el('p', { text: String(err && err.message || err) }),
    el('p', { class: 'caption', text: 'Make sure the site is served over http:// (not opened as a file://) so fetch can read ./data/*.json.' }),
  ]));
}

function wireChrome() {
  /* hamburger */
  const ham = $('#navHamburger');
  const mobile = $('#navMobile');
  ham.addEventListener('click', () => {
    const open = mobile.classList.toggle('is-open');
    ham.setAttribute('aria-expanded', open ? 'true' : 'false');
  });
  $$('.nav-mobile-link').forEach((l) => l.addEventListener('click', () => {
    mobile.classList.remove('is-open');
    ham.setAttribute('aria-expanded', 'false');
  }));

  /* modal: backdrop click + esc */
  $('#modalBackdrop').addEventListener('click', (e) => { if (e.target === e.currentTarget) closeModal(); });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('#modalBackdrop').hidden) closeModal();
  });

  /* footer: last refresh + freshness */
  const meta = STATE.meta;
  if (meta) {
    const fresh = refreshInfo(meta.built_at);
    const fb = $('#footerBuilt');
    if (fb) fb.textContent = `Prices last refreshed ${(meta.built_at || '').slice(0, 10)} · ${fresh.label}`;
  }
}

async function boot() {
  showLoading();
  try {
    await loadData();
    wireChrome();
    window.addEventListener('hashchange', router);
    router();
  } catch (err) {
    console.error('[Poke Research] boot failed:', err);
    showError(err);
  }
}

document.addEventListener('DOMContentLoaded', boot);
