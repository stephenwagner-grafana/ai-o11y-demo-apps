// neoncart-non-ai.js
//
// K6 scenario for the 150 non-AI NeonCart users. None of these requests
// invoke the chatbot or the gift-finder — these users just browse and buy.
//
// Journey weights (from docs/LOADGEN.md):
//   40% quick browser      — land, view 1-2 products, leave
//   25% searcher           — search, view results, 30% buy
//   20% browser-shopper    — browse categories, view 3-5, add 1-2, 60% buy
//   10% direct purchaser   — search specific, add, checkout fast, 90% buy
//    5% abandoned cart     — land, add, leave
//
// Variation:
//   - 3-15 s inter-step delay (uniform), occasional 30 s ponder
//   - 1-7 product views per session
//   - 1-4 items per cart
//   - ±10 % rate jitter via constant-arrival-rate
//
// Required header on every request: X-Caller-Type: synthetic (set by _common.js).

import { check, group, sleep } from 'k6';
import {
  request, sleepStep, sleepPonder, pickWeighted, pickOne, randInt, shuffle,
  randSessionId, loadUsers, nominalSessionsPerHour,
} from './_common.js';

// ── init context ──────────────────────────────────────────────────────────────

const users = loadUsers();   // array of user objects from orchestrator
const BASE = __ENV.NC_BASE_URL || 'http://nc-web.neoncart.svc.cluster.local';

// ── k6 options ────────────────────────────────────────────────────────────────

// Arrival rate: sessions per second; pre-allocated VUs cover bursts.
// One iteration = one synthetic session.
const sph = nominalSessionsPerHour();
const ratePerSecond = Math.max(sph / 3600, 0.001);   // never zero
export const options = {
  scenarios: {
    nc_non_ai: {
      executor: 'constant-arrival-rate',
      rate: Math.max(1, Math.round(ratePerSecond * 60)),    // sessions per minute
      timeUnit: '1m',
      duration: '24h',                                       // restarted by orchestrator
      preAllocatedVUs: Math.max(4, Math.ceil(ratePerSecond * 30)),
      maxVUs: Math.max(20, Math.ceil(ratePerSecond * 120)),
      exec: 'session',
    },
  },
  noConnectionReuse: false,
  discardResponseBodies: false,
};

// ── search terms / category slugs used across journeys ───────────────────────

const SEARCH_TERMS = [
  'wireless headphones', 'mechanical keyboard', 'gaming mouse',
  'usb-c cable', 'monitor 27 inch', 'webcam', 'desk lamp',
  'standing desk mat', 'laptop sleeve', 'noise cancelling',
  'bluetooth speaker', 'phone charger', 'ergonomic chair',
  'smart bulb', 'docking station', 'external ssd',
];

const CATEGORY_SLUGS = [
  'audio', 'computers', 'peripherals', 'mobile', 'wearables',
  'accessories', 'gaming', 'smart-home', 'displays', 'storage',
];

// SKUs are unknown to the loadgen — we discover them by listing products and
// drilling in. The script just needs a "an SKU we can add to cart" path. If
// the catalog endpoint returns 0 products (Phase 1 stub), the script no-ops
// the buy step gracefully.

// ── helpers ───────────────────────────────────────────────────────────────────

function pickUser() {
  return users[Math.floor(Math.random() * users.length)];
}

function listProducts(user, sessionId) {
  const r = request('GET', `${BASE}/api/products`, null, user, sessionId);
  check(r, { 'products 2xx': (res) => res.status >= 200 && res.status < 300 });
  try { return (r.json('products') || []); } catch (_) { return []; }
}

function search(user, sessionId, q) {
  const url = `${BASE}/api/search?q=${encodeURIComponent(q)}`;
  const r = request('GET', url, null, user, sessionId);
  check(r, { 'search 2xx': (res) => res.status >= 200 && res.status < 300 });
  try { return (r.json('results') || []); } catch (_) { return []; }
}

function viewProduct(user, sessionId, sku) {
  const r = request('GET', `${BASE}/api/products/${encodeURIComponent(sku)}`, null, user, sessionId);
  // 404s are fine if the catalog endpoint stub returns empties.
  check(r, { 'product status known': (res) => res.status === 200 || res.status === 404 });
  return r;
}

function viewCart(user, sessionId) {
  return request('GET', `${BASE}/api/cart/guest`, null, user, sessionId);
}

function addToCart(user, sessionId, sku) {
  if (!sku) return null;
  return request('POST', `${BASE}/api/cart/add`, {
    sku,
    quantity: randInt(1, 2),
    source: 'manual',
  }, user, sessionId);
}

function checkout(user, sessionId, items) {
  return request('POST', `${BASE}/api/orders`, { items }, user, sessionId);
}

function pickSkuFromList(list) {
  if (!list || list.length === 0) return null;
  const p = list[Math.floor(Math.random() * list.length)];
  return p && (p.sku || p.id) ? (p.sku || p.id) : null;
}

// ── journeys ──────────────────────────────────────────────────────────────────

function journeyQuickBrowser(user, sessionId) {
  group('quick-browser', () => {
    request('GET', `${BASE}/`, null, user, sessionId);
    sleepStep();
    const products = listProducts(user, sessionId);
    sleepStep();
    const n = randInt(1, 2);
    for (let i = 0; i < n; i++) {
      const sku = pickSkuFromList(products);
      if (sku) viewProduct(user, sessionId, sku);
      sleepStep();
    }
  });
}

function journeySearcher(user, sessionId) {
  group('searcher', () => {
    request('GET', `${BASE}/`, null, user, sessionId);
    sleepStep();
    const term = pickOne(SEARCH_TERMS);
    const results = search(user, sessionId, term);
    sleepStep();
    let viewedSku = null;
    if (Math.random() < 0.7 && results.length > 0) {
      viewedSku = pickSkuFromList(results);
      if (viewedSku) viewProduct(user, sessionId, viewedSku);
      sleepStep();
    }
    if (Math.random() < 0.3 && viewedSku) {
      addToCart(user, sessionId, viewedSku);
      sleepShortPonder();
      checkout(user, sessionId, [{ sku: viewedSku, quantity: 1 }]);
    }
  });
}

function journeyBrowserShopper(user, sessionId) {
  group('browser-shopper', () => {
    request('GET', `${BASE}/`, null, user, sessionId);
    sleepStep();
    // Browse 2 category-ish lists (we just hit /api/products with a query)
    for (let i = 0; i < 2; i++) {
      const cat = pickOne(CATEGORY_SLUGS);
      search(user, sessionId, cat);
      sleepStep();
    }
    const products = listProducts(user, sessionId);
    const viewCount = randInt(3, 5);
    const addCount = randInt(1, 2);
    const seen = [];
    for (let i = 0; i < viewCount; i++) {
      const sku = pickSkuFromList(products);
      if (sku) {
        viewProduct(user, sessionId, sku);
        seen.push(sku);
      }
      sleepStep();
    }
    const skusToAdd = shuffle(seen).slice(0, addCount);
    for (const sku of skusToAdd) {
      addToCart(user, sessionId, sku);
      sleepStep();
    }
    if (Math.random() < 0.6 && skusToAdd.length > 0) {
      sleepPonder();
      checkout(user, sessionId, skusToAdd.map((sku) => ({ sku, quantity: 1 })));
    }
  });
}

function journeyDirectPurchaser(user, sessionId) {
  group('direct-purchaser', () => {
    request('GET', `${BASE}/`, null, user, sessionId);
    const term = pickOne(SEARCH_TERMS);
    const results = search(user, sessionId, term);
    const sku = pickSkuFromList(results) || pickSkuFromList(listProducts(user, sessionId));
    sleepStep();
    if (sku) {
      viewProduct(user, sessionId, sku);
      sleepStep();
      addToCart(user, sessionId, sku);
      sleepStep();
      if (Math.random() < 0.9) {
        checkout(user, sessionId, [{ sku, quantity: 1 }]);
      }
    }
  });
}

function journeyAbandonedCart(user, sessionId) {
  group('abandoned-cart', () => {
    request('GET', `${BASE}/`, null, user, sessionId);
    sleepStep();
    const products = listProducts(user, sessionId);
    const sku = pickSkuFromList(products);
    if (sku) {
      addToCart(user, sessionId, sku);
      sleepStep();
      viewCart(user, sessionId);
    }
    // user just leaves — no checkout
  });
}

function sleepShortPonder() {
  // 8-18 s — mid-length thinking before checkout.
  sleep(8 + Math.random() * 10);
}

// ── entrypoint ────────────────────────────────────────────────────────────────

export function session() {
  if (users.length === 0) {
    // No users in this cohort — nothing to do this iteration.
    sleep(60);
    return;
  }
  const user = pickUser();
  const sessionId = randSessionId();
  const journey = pickWeighted([
    { value: 'quick',   weight: 40 },
    { value: 'search',  weight: 25 },
    { value: 'browse',  weight: 20 },
    { value: 'direct',  weight: 10 },
    { value: 'abandon', weight: 5 },
  ]);
  switch (journey) {
    case 'quick':   journeyQuickBrowser(user, sessionId); break;
    case 'search':  journeySearcher(user, sessionId); break;
    case 'browse':  journeyBrowserShopper(user, sessionId); break;
    case 'direct':  journeyDirectPurchaser(user, sessionId); break;
    case 'abandon': journeyAbandonedCart(user, sessionId); break;
  }
}
