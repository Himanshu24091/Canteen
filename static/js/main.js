// ─── Theme ────────────────────────────────────────────────────────────────
const html = document.documentElement;
const themeToggle = document.getElementById('themeToggle');
const themeIcon = document.getElementById('themeIcon');

function applyTheme(theme) {
  html.setAttribute('data-theme', theme);
  localStorage.setItem('theme', theme);
  if (themeIcon) {
    themeIcon.className = theme === 'dark' ? 'fas fa-sun' : 'fas fa-moon';
  }
}

applyTheme(localStorage.getItem('theme') || 'dark');
if (themeToggle) {
  themeToggle.addEventListener('click', () => {
    applyTheme(html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
  });
}

// ─── Sidebar ──────────────────────────────────────────────────────────────
const sidebar = document.getElementById('sidebar');
const hamburger = document.getElementById('hamburger');
const sidebarClose = document.getElementById('sidebarClose');
const overlay = document.getElementById('sidebarOverlay');

function openSidebar() {
  sidebar?.classList.add('open');
  overlay?.classList.add('open');
}
function closeSidebar() {
  sidebar?.classList.remove('open');
  overlay?.classList.remove('open');
}

hamburger?.addEventListener('click', openSidebar);
sidebarClose?.addEventListener('click', closeSidebar);
overlay?.addEventListener('click', closeSidebar);

// ─── Toast ────────────────────────────────────────────────────────────────
function showToast(message, type = 'info') {
  let container = document.querySelector('.toast-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  const icons = { success: 'check-circle', error: 'exclamation-circle', info: 'info-circle', warning: 'exclamation-triangle' };
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<i class="fas fa-${icons[type] || 'info-circle'}"></i> ${message}`;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3500);
}

// ─── Cart (localStorage) ──────────────────────────────────────────────────
const CART_KEY = 'canteen_cart';

function getCart() {
  try { return JSON.parse(localStorage.getItem(CART_KEY) || '[]'); }
  catch { return []; }
}

function saveCart(cart) {
  localStorage.setItem(CART_KEY, JSON.stringify(cart));
  updateCartBadges();
}

function addToCart(id, name, price) {
  const cart = getCart();
  const existing = cart.find(i => i.id === id);
  if (existing) { existing.qty += 1; }
  else { cart.push({ id, name, price, qty: 1 }); }
  saveCart(cart);
  showToast(`${name} added to cart!`, 'success');
}

function removeFromCart(id) {
  saveCart(getCart().filter(i => i.id !== id));
}

function updateQty(id, delta) {
  const cart = getCart();
  const item = cart.find(i => i.id === id);
  if (item) {
    item.qty += delta;
    if (item.qty <= 0) return removeFromCart(id);
  }
  saveCart(cart);
}

function updateCartBadges() {
  const cart = getCart();
  const count = cart.reduce((s, i) => s + i.qty, 0);
  document.querySelectorAll('#navCartCount, #topbarCartCount').forEach(el => {
    el.textContent = count;
    el.style.display = count > 0 ? 'inline-flex' : 'none';
  });
}

updateCartBadges();

// ─── Auto-dismiss flashes ──────────────────────────────────────────────────
setTimeout(() => {
  document.querySelectorAll('.alert').forEach(a => {
    a.style.transition = 'opacity 0.5s';
    a.style.opacity = '0';
    setTimeout(() => a.remove(), 500);
  });
}, 4000);

// ─── Idle Auto-Logout ──────────────────────────────────────────────────────
(function() {
  // Only run for logged-in pages (sidebar exists)
  if (!document.getElementById('sidebar')) return;

  const IDLE_LIMIT    = 60 * 60 * 1000;   // 60 min — must match server IDLE_TIMEOUT_SECONDS
  const WARN_BEFORE   = 10 * 60 * 1000;   // show warning 10 min before logout
  const WARN_AT       = IDLE_LIMIT - WARN_BEFORE;  // 50 min
  const PING_INTERVAL = 5  * 60 * 1000;   // ping server every 5 min IF user is active

  let idleTimer    = null;
  let warnTimer    = null;
  let countdown    = null;
  let warnShown    = false;
  let secsLeft     = WARN_BEFORE / 1000;
  let lastActive   = Date.now(); // track last real user activity


  // ── Build warning modal ──────────────────────────────────────
  const modal = document.createElement('div');
  modal.id = 'idleModal';
  modal.style.cssText = `
    display:none;position:fixed;inset:0;z-index:9999;
    background:rgba(0,0,0,0.75);align-items:center;justify-content:center;
  `;
  modal.innerHTML = `
    <div style="
      background:var(--bg-card);border:1px solid var(--border);
      border-radius:16px;padding:32px;max-width:400px;width:90%;
      text-align:center;box-shadow:0 20px 60px rgba(0,0,0,0.5);
      animation:scaleIn 0.25s ease;
    ">
      <div style="font-size:52px;margin-bottom:12px;">⏰</div>
      <h2 style="font-size:20px;font-weight:800;margin-bottom:8px;color:var(--text-primary);">
        Session Expiring Soon
      </h2>
      <p style="font-size:14px;color:var(--text-secondary);margin-bottom:20px;line-height:1.6;">
        You've been inactive. You'll be logged out automatically in
      </p>
      <div id="idleCountdown" style="
        font-size:42px;font-weight:900;
        background:linear-gradient(135deg,var(--accent),#fbbf24);
        -webkit-background-clip:text;background-clip:text;
        -webkit-text-fill-color:transparent;
        margin-bottom:24px;
      ">10:00</div>
      <div style="display:flex;gap:12px;justify-content:center;flex-wrap:wrap;">
        <button id="idleStay" style="
          padding:10px 28px;border-radius:99px;border:none;cursor:pointer;
          background:var(--accent);color:#fff;font-size:15px;font-weight:700;
          font-family:inherit;transition:all 0.2s;
        ">
          <i class="fas fa-check"></i> Stay Logged In
        </button>
        <a href="/logout" style="
          padding:10px 28px;border-radius:99px;
          border:1px solid var(--border);color:var(--text-secondary);
          font-size:15px;font-weight:600;display:inline-flex;
          align-items:center;gap:6px;
        ">
          <i class="fas fa-sign-out-alt"></i> Logout Now
        </a>
      </div>
    </div>
  `;
  document.body.appendChild(modal);

  // ── Helper: format mm:ss ─────────────────────────────────────
  function fmt(s) {
    const m = Math.floor(s / 60);
    return `${String(m).padStart(2,'0')}:${String(s % 60).padStart(2,'0')}`;
  }

  // ── Show warning modal ────────────────────────────────────────
  function showWarn() {
    if (warnShown) return;
    warnShown = true;
    secsLeft = WARN_BEFORE / 1000;
    modal.style.display = 'flex';
    document.getElementById('idleCountdown').textContent = fmt(secsLeft);

    countdown = setInterval(() => {
      secsLeft--;
      document.getElementById('idleCountdown').textContent = fmt(Math.max(0, secsLeft));
      if (secsLeft <= 0) {
        clearInterval(countdown);
        window.location.href = '/logout?reason=idle';
      }
    }, 1000);
  }

  // ── Hide warning & reset ──────────────────────────────────────
  function dismissWarn() {
    modal.style.display = 'none';
    warnShown = false;
    clearInterval(countdown);
    resetTimers();
    // Ping server to refresh last_activity
    fetch('/api/keep-alive', { method: 'POST' }).catch(() => {});
  }

  // ── Reset idle timers on any activity ───────────────────────
  function resetTimers() {
    clearTimeout(warnTimer);
    clearTimeout(idleTimer);
    if (!warnShown) {
      warnTimer = setTimeout(showWarn, WARN_AT);
      idleTimer = setTimeout(() => { window.location.href = '/logout?reason=idle'; }, IDLE_LIMIT);
    }
  }

  // ── Activity events: reset CLIENT timer + track lastActive ─
  ['mousemove','mousedown','keydown','touchstart','scroll','click'].forEach(ev => {
    document.addEventListener(ev, () => {
      lastActive = Date.now();
      if (!warnShown) resetTimers();
    }, { passive: true });
  });

  // ── Stay button ─────────────────────────────────────────────
  document.getElementById('idleStay').addEventListener('click', dismissWarn);

  // ── Periodic server ping (every 5 min, only if user was recently active) ──
  // This keeps server-side last_activity in sync when user is on one page.
  // If user has been idle > (IDLE_LIMIT - PING_INTERVAL), stop pinging — let server expire.
  setInterval(() => {
    const idleSince = Date.now() - lastActive;
    if (idleSince < (IDLE_LIMIT - PING_INTERVAL)) {
      // User was active recently — keep server session alive
      fetch('/api/keep-alive', { method: 'POST' }).catch(() => {});
    }
    // If idle too long — don't ping. Server will expire on next page load.
  }, PING_INTERVAL);

  // ── Start ───────────────────────────────────────────────────
  resetTimers();
})();
