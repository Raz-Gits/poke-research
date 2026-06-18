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
  byId: new Map(), loaded: false, error: null,
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
  const updated = (meta.built_for_date || meta.built_at || '').slice(0, 10);
  const statRow = el('div', { class: 'stat-row container' }, [
    statCard('bg-yellow', 'Tracked', meta.cards.toLocaleString(), 'cards in the corpus'),
    statCard('bg-teal', 'Coverage', String(meta.sets), 'Scarlet & Violet sets'),
    statCard('bg-coral', 'Cadence', 'Daily', `prices updated ${updated || 'daily'}`),
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
      explainerCard('bg-yellow', '◎', 'Sealed EV', 'Per-card pull rates × market prices roll up to an expected value per pack and box, versus the real box price.'),
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
    el('th', { class: 'num', text: 'Box price' }),
    el('th', { class: 'num', text: 'EV / pack' }),
    el('th', { class: 'num', text: 'EV / box' }),
    el('th', { class: 'num', text: 'Verdict' }),
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
          el('div', { class: 'lb-sub', text: `${s.series} · ${s.packs_per_box} packs/box` }),
        ]),
      ])),
      el('td', { class: 'num lb-price', text: USD0(s.box_price) }),
      el('td', { class: 'num lb-price', text: USD(s.raw_value_per_pack) }),
      el('td', { class: 'num lb-price', text: USD0(s.ev_per_box) }),
      el('td', { class: 'num' }, evSignalPill(s.signal_pct)),
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
          'Sealed expected value = Σ (per-card pull rate × market price) × packs per box, vs the real box price. Green “Undervalued” = the cards inside are worth more than the sealed box (good to rip / hold); red “Overvalued” = you pay a premium for sealed (buy singles). A value signal, not a price-trend forecast.' }),
      ]),
      el('span', { class: 'chip chip--teal', text: 'live · pokemontcg.io' }),
    ]),
    table,
    el('p', { class: 'caption', html: 'Pull rates are an <strong>estimate</strong> (configurable per rarity tier); they are not official pull rates. Box / pack prices are seeded market estimates.' }),
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
   4. MOVERS — stub with awaiting-data badge
   ============================================================ */
function viewMovers() {
  const lb = STATE.leaderboard;
  const awaiting = lb.movers.length && lb.movers.every((m) => m.awaiting_data);

  const banner = el('div', { class: 'table-card', style: 'padding:20px 24px;display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin-bottom:24px;box-shadow:none;background:var(--surface-soft)' }, [
    el('span', { class: 'badge-stub', text: 'awaiting eBay data' }),
    el('p', { class: 'body-sm', style: 'margin:0;color:var(--slate);max-width:62ch', html:
      'Real day-over-day movers need the <strong>eBay Browse API</strong> (active-listing snapshots, diffed daily to estimate sold/unsold) — which isn’t wired yet. Until then we fall back to the cards whose market price diverges most from the model.' }),
  ]);

  const section = el('section', { class: 'section container' }, [
    el('div', { class: 'section-head' }, [
      el('div', {}, [
        el('p', { class: 'micro section-eyebrow', text: 'Movers' }),
        el('h2', { class: 'h2', text: 'Biggest market movers' }),
        el('p', { class: 'section-sub', text:
          'When supply data lands, this ranks cards by 7-day vs 30-day listing-supply shift (loosening vs tightening). For now it shows the largest price-vs-model gaps as a placeholder basis.' }),
      ]),
      awaiting ? el('span', { class: 'badge-stub', text: 'stub · price fallback' }) : el('span', { class: 'chip chip--teal', text: 'live' }),
    ]),
    banner,
    leaderboardTable(lb.movers, { deltaLabel: 'Price gap' }),
    el('p', { class: 'caption', html: `Basis: <code>${lb.movers_basis || 'price_signal_fallback'}</code> — a stand-in until supply-saturation data exists. No eBay / sold-comp feed is implied.` }),
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

  /* gauges: demand pressure + supply saturation from card.dynamics (stubbed) */
  const dyn = card.dynamics || {};
  const stub = dyn.status === 'awaiting_data' || dyn.demand_pressure == null;
  const gauges = el('div', { class: 'gauges' }, [
    gauge('Demand pressure', dyn.demand_pressure, 0.20, stub, '%'),
    gauge('Supply saturation', dyn.supply_saturation != null ? dyn.supply_saturation - 1 : null, 0.5, stub, '×', dyn.supply_saturation),
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
        el('div', { class: 'iq-row' }, [
          el('span', { class: 'iq-badge' }, [
            el('span', { class: 'iq-num', text: card.iq_score != null ? card.iq_score.toFixed(0) : '—' }),
            el('span', { class: 'iq-of', text: '/ 100 IQ' }),
          ]),
          el('span', { class: 'caption', text: 'composite of scarcity, character premium & in-set rank' }),
        ]),
        gauges,
        el('p', { class: 'caption', html: 'Demand pressure & supply saturation need an eBay feed — shown as <strong>awaiting data</strong>.' }),
        signalsPanel,
      ]),
    ]),
  ]);
}

function gauge(label, value, max, isStub, unit, rawDisplay) {
  const pct = (!isStub && value != null) ? Math.max(0, Math.min(1, (value + (unit === '×' ? max : 0)) / (unit === '×' ? max * 2 : max))) : 0.5;
  const fill = el('div', { class: `gauge-fill${isStub ? ' is-stub' : ''}`, style: `width:${(isStub ? 100 : pct * 100).toFixed(0)}%` });
  let readout;
  if (isStub) readout = 'awaiting data';
  else if (unit === '×') readout = `${(rawDisplay ?? 1).toFixed(2)}× (>1 loosening, <1 tightening)`;
  else readout = PCT(value);
  return el('div', { class: 'gauge' }, [
    el('div', { class: 'gauge-head' }, [
      el('span', { class: 'gauge-label', text: label }),
      isStub ? el('span', { class: 'badge-stub', text: 'stub' }) : el('span', { class: 'chip chip--teal', text: 'est' }),
    ]),
    el('div', { class: 'gauge-bar' }, fill),
    el('div', { class: 'gauge-value', text: readout }),
  ]);
}

function fmtFeat(f, v) {
  if (v == null) return '—';
  if (f === 'pull_cost') return USD0(v);
  if (f === 'set_rank') return v.toFixed(2);
  if (f === 'months_since_release') return `${v.toFixed(0)} mo`;
  return v.toFixed(2);
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

  /* footer build date */
  const meta = STATE.meta;
  if (meta) {
    const built = (meta.built_at || '').slice(0, 10);
    const fb = $('#footerBuilt');
    if (fb) fb.textContent = `Built ${built || '—'}`;
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
