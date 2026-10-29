import React, { useEffect, useState, useMemo, useRef } from 'react';
import { Html5Qrcode } from 'html5-qrcode';

const rawApi = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';
function getApiUrl() {
  if (typeof window !== 'undefined' && window.location) {
    const host = window.location.hostname;
    if (host && host !== 'localhost' && host !== '127.0.0.1') {
      try {
        const u = new URL(rawApi);
        if (u.hostname === 'localhost' || u.hostname === '127.0.0.1') {
          return `${window.location.protocol}//${host}:${u.port || 8000}`;
        }
      } catch {}
    }
  }
  return rawApi;
}
const API = getApiUrl();
const getToken = () => localStorage.getItem('xf_token');

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (getToken()) headers.Authorization = `Bearer ${getToken()}`;
  if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json';
  const res = await fetch(`${API}${path}`, { ...options, headers });
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      msg = body.detail || msg;
    } catch {}
    throw new Error(msg);
  }
  const type = res.headers.get('content-type') || '';
  return type.includes('application/json') ? res.json() : res;
}

function saveSession(data) {
  localStorage.setItem('xf_token', data.access_token);
  localStorage.setItem('xf_user', JSON.stringify(data.user));
}

function money(n) {
  return `₹${Number(n || 0).toFixed(2)}`;
}

function parseShopIdFromQr(text) {
  if (!text) return null;
  const raw = String(text).trim();
  try {
    const url = new URL(raw);
    const shopParam = url.searchParams.get('shop');
    if (shopParam && !isNaN(Number(shopParam))) return shopParam;
    const parts = url.pathname.split('/').filter(Boolean);
    const last = parts[parts.length - 1];
    if (last && !isNaN(Number(last))) return last;
  } catch {}
  try {
    const data = JSON.parse(raw);
    if (data && data.shop_id) return String(data.shop_id);
    if (data && data.shop) return String(data.shop);
  } catch {}
  const match = raw.match(/(?:[?&]shop=|^shop=)(\d+)/i);
  if (match) return match[1];
  if (/^\d+$/.test(raw)) return raw;
  return null;
}

export default function App() {
  const [user, setUser] = useState(() => {
    try { return JSON.parse(localStorage.getItem('xf_user')); } catch { return null; }
  });
  const [mode, setMode] = useState('login');
  const [role, setRole] = useState('customer');
  const [form, setForm] = useState({ name: '', email: '', phone: '', password: '', shop_name: '', address: '' });
  const [shop, setShop] = useState(null);
  const [shops, setShops] = useState([]);
  const [orders, setOrders] = useState([]);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  // Advanced order form state
  const [orderForm, setOrderForm] = useState({
    shop_id: new URLSearchParams(window.location.search).get('shop') || '',
    copies: 1,
    pages: 'all',
    color_mode: 'bw',
    paper_size: 'A4',
    sides: 'single',
    orientation: 'portrait',
    finishing: 'none',
    notes: ''
  });
  const [uploadFile, setUploadFile] = useState(null);
  const [liveEstimate, setLiveEstimate] = useState(null);
  const [estimating, setEstimating] = useState(false);

  // Navigation tab
  const [tab, setTab] = useState(() => {
    return new URLSearchParams(window.location.search).get('shop') ? 'new' : 'overview';
  });

  // Shopkeeper QR preview states
  const [qrBlobUrl, setQrBlobUrl] = useState('');
  const [qrTargetUrl, setQrTargetUrl] = useState('');
  const [qrLoading, setQrLoading] = useState(false);
  const [qrError, setQrError] = useState('');

  // Filtering and search states for orders
  const [orderFilter, setOrderFilter] = useState('all');
  const [orderSearch, setOrderSearch] = useState('');
  const [orderDateRange, setOrderDateRange] = useState('all');

  // Modal states: detail & receipt
  const [selectedOrder, setSelectedOrder] = useState(null);
  const [receiptData, setReceiptData] = useState(null);
  const [quoteInput, setQuoteInput] = useState('');
  const [showPayModal, setShowPayModal] = useState(false);

  // Phase 3: Scanner & Direct QR-to-Document Upload States
  const [showScanner, setShowScanner] = useState(false);
  const [directShopId, setDirectShopId] = useState(() => {
    if (typeof window === 'undefined') return '';
    const params = new URLSearchParams(window.location.search);
    if (params.get('shop')) return params.get('shop');
    const parts = window.location.pathname.split('/').filter(Boolean);
    if (parts.length >= 2 && !isNaN(Number(parts[parts.length - 1]))) {
      return parts[parts.length - 1];
    }
    return '';
  });
  const [directShop, setDirectShop] = useState(null);
  const [directShopLoading, setDirectShopLoading] = useState(false);
  const [directShopError, setDirectShopError] = useState('');

  useEffect(() => {
    if (!directShopId) {
      setDirectShop(null);
      setDirectShopError('');
      return;
    }
    let isMounted = true;
    setDirectShopLoading(true);
    setDirectShopError('');
    request(`/api/shops/${directShopId}`)
      .then(s => {
        if (isMounted) {
          setDirectShop(s);
          try {
            const url = new URL(window.location.href);
            if (url.searchParams.get('shop') !== String(directShopId)) {
              url.searchParams.set('shop', directShopId);
              window.history.pushState({}, '', url.pathname.includes('/customer/upload') ? url.toString() : `/customer/upload?shop=${directShopId}`);
            }
          } catch {}
        }
      })
      .catch(err => {
        if (isMounted) {
          setDirectShopError(err.message || 'Shop not found or currently inactive');
          setDirectShop(null);
        }
      })
      .finally(() => {
        if (isMounted) setDirectShopLoading(false);
      });

    return () => { isMounted = false; };
  }, [directShopId]);

  function handleScannerSuccess(scannedShopId) {
    setShowScanner(false);
    setDirectShopId(scannedShopId);
    try {
      window.history.pushState({}, '', `/customer/upload?shop=${scannedShopId}`);
    } catch {}
    setMessage(`✓ Connected to Shop #${scannedShopId}!`);
  }

  function handleExitDirectUpload() {
    setDirectShopId('');
    try {
      window.history.pushState({}, '', '/');
    } catch {}
  }

  const field = (key, value) => setForm(old => ({ ...old, [key]: value }));

  async function loadDashboard() {
    if (!user) return;
    try {
      const [s, o] = await Promise.all([request('/api/shops'), request('/api/orders')]);
      setShops(s);
      setOrders(o);
      if (user.role === 'shopkeeper') {
        const myShop = await request('/api/shopkeeper/shop');
        setShop(myShop);
      }
    } catch (e) {
      setError(e.message);
    }
  }

  async function loadQR() {
    if (user?.role !== 'shopkeeper') return;
    setQrLoading(true);
    setQrError('');
    try {
      const origin = window.location.origin;
      const res = await request(`/api/shopkeeper/qr?base_url=${encodeURIComponent(origin)}`);
      const targetUrl = res.headers.get('x-shop-order-url') || '';
      if (targetUrl) setQrTargetUrl(targetUrl);
      const blob = await res.blob();
      const objUrl = URL.createObjectURL(blob);
      setQrBlobUrl(prev => {
        if (prev) URL.revokeObjectURL(prev);
        return objUrl;
      });
    } catch (e) {
      setQrError(e.message || 'Failed to load QR code');
    } finally {
      setQrLoading(false);
    }
  }

  useEffect(() => { loadDashboard(); }, [user?.id]);

  useEffect(() => {
    if (user?.role === 'shopkeeper' && shop) {
      loadQR();
    }
  }, [user?.role, shop?.id]);

  useEffect(() => {
    request('/api/shops').then(s => {
      setShops(s);
      const urlShop = new URLSearchParams(window.location.search).get('shop');
      if (urlShop) {
        setOrderForm(f => ({ ...f, shop_id: urlShop }));
      }
    }).catch(() => {});
  }, []);

  useEffect(() => {
    const urlShop = new URLSearchParams(window.location.search).get('shop');
    if (urlShop && user?.role === 'customer') {
      setTab('new');
    }
  }, [user?.id]);

  useEffect(() => {
    return () => {
      if (qrBlobUrl) URL.revokeObjectURL(qrBlobUrl);
    };
  }, [qrBlobUrl]);

  // Live price estimate calculation whenever order options change
  useEffect(() => {
    if (!orderForm.shop_id) {
      setLiveEstimate(null);
      return;
    }
    const timer = setTimeout(async () => {
      setEstimating(true);
      try {
        const est = await request('/api/pricing/estimate', {
          method: 'POST',
          body: JSON.stringify({
            shop_id: Number(orderForm.shop_id),
            copies: Number(orderForm.copies || 1),
            pages: orderForm.pages || 'all',
            color_mode: orderForm.color_mode,
            paper_size: orderForm.paper_size,
            sides: orderForm.sides,
            orientation: orderForm.orientation,
            finishing: orderForm.finishing
          })
        });
        setLiveEstimate(est);
      } catch (e) {
        setLiveEstimate(null);
      } finally {
        setEstimating(false);
      }
    }, 250);

    return () => clearTimeout(timer);
  }, [
    orderForm.shop_id,
    orderForm.copies,
    orderForm.pages,
    orderForm.color_mode,
    orderForm.paper_size,
    orderForm.sides,
    orderForm.orientation,
    orderForm.finishing
  ]);

  async function submitAuth(e) {
    e.preventDefault(); setError(''); setMessage(''); setBusy(true);
    try {
      let path, body;
      if (mode === 'register' && role === 'customer') {
        path = '/api/auth/register/customer';
        body = { name: form.name, email: form.email, phone: form.phone, password: form.password };
      } else if (mode === 'register') {
        path = '/api/auth/register/shopkeeper';
        body = { name: form.name, email: form.email, phone: form.phone, password: form.password, shop_name: form.shop_name, address: form.address };
      } else {
        path = '/api/auth/login';
        body = { email: form.email, password: form.password };
      }
      const data = await request(path, { method: 'POST', body: JSON.stringify(body) });
      if (mode === 'login' && data.user.role !== role) {
        throw new Error(`This account is registered as ${data.user.role}. Choose the matching role.`);
      }
      saveSession(data);
      setUser(data.user);
      setShop(data.shop || null);
      setMessage('Welcome to XeroxFlow!');
      const urlShop = new URLSearchParams(window.location.search).get('shop');
      setTab(urlShop && data.user.role === 'customer' ? 'new' : 'overview');
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  function logout() {
    localStorage.removeItem('xf_token');
    localStorage.removeItem('xf_user');
    setUser(null); setShop(null); setOrders([]); setMode('login'); setError(''); setMessage('You have logged out.');
    if (qrBlobUrl) URL.revokeObjectURL(qrBlobUrl);
    setQrBlobUrl(''); setQrTargetUrl('');
  }

  async function refresh() {
    setError('');
    try {
      await loadDashboard();
      if (user?.role === 'shopkeeper') await loadQR();
      setMessage('Dashboard refreshed.');
    } catch (e) {
      setError(e.message);
    }
  }

  async function createOrder(e) {
    e.preventDefault(); setError(''); setMessage('');
    if (!uploadFile) { setError('Choose a document first.'); return; }
    if (!orderForm.shop_id) { setError('Choose a Xerox shop.'); return; }

    const fd = new FormData();
    Object.entries(orderForm).forEach(([k, v]) => fd.append(k, v));
    fd.append('document', uploadFile);
    setBusy(true);

    try {
      const created = await request('/api/orders', { method: 'POST', body: fd });
      setMessage(`Order #${created.id} submitted successfully! Track progress below.`);
      setUploadFile(null);
      const fileInput = window.document.getElementById('file-upload-input');
      if (fileInput) fileInput.value = '';
      setTab('orders');
      await loadDashboard();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function changeStatus(order, targetStatus, reason = '', quotePrice = null, paymentStatus = '') {
    setError(''); setMessage('');
    try {
      const payload = { status_value: targetStatus };
      if (reason) payload.reason = reason;
      if (quotePrice !== null) payload.quote_price = Number(quotePrice);
      if (paymentStatus) payload.payment_status = paymentStatus;

      const updated = await request(`/api/orders/${order.id}/status`, {
        method: 'PATCH',
        body: JSON.stringify(payload)
      });
      setMessage(`Order #${order.id} status updated to ${targetStatus}.`);
      if (selectedOrder && selectedOrder.id === order.id) {
        setSelectedOrder(updated);
      }
      await loadDashboard();
    } catch (e) {
      setError(e.message);
    }
  }

  async function markPaymentDone(order) {
    const orderId = order.id || order.order_id;
    const amountVal = order.final_amount_inr || order.final_price || order.estimated_price;
    const amountStr = money(amountVal);
    const confirmed = window.confirm(
      `Confirm payment received for Order #${orderId}?\n\nAmount: ${amountStr}\n\nThis will mark the order's payment status as PAID.`
    );
    if (!confirmed) return;

    setError(''); setMessage('');
    try {
      const updated = await request(`/api/orders/${orderId}/payment`, {
        method: 'POST',
        body: JSON.stringify({ payment_status: 'paid' })
      });
      setMessage(`Payment for Order #${orderId} has been successfully recorded as PAID.`);
      if (selectedOrder && selectedOrder.id === orderId) {
        setSelectedOrder(updated);
      }
      if (receiptData && receiptData.order_id === orderId) {
        setReceiptData({ ...receiptData, payment_status: 'paid', paid_at: updated.paid_at });
      }
      await loadDashboard();
    } catch (e) {
      setError(e.message || 'Failed to update payment status');
    }
  }

  async function updatePaymentStatus(order, paymentStatus) {
    setError(''); setMessage('');
    try {
      const updated = await request(`/api/orders/${order.id}/payment`, {
        method: 'POST',
        body: JSON.stringify({ payment_status: paymentStatus })
      });
      setMessage(`Order #${order.id} payment status set to ${paymentStatus.toUpperCase()}.`);
      if (selectedOrder && selectedOrder.id === order.id) {
        setSelectedOrder(updated);
      }
      if (receiptData && receiptData.order_id === order.id) {
        setReceiptData({ ...receiptData, payment_status: paymentStatus, paid_at: updated.paid_at });
      }
      await loadDashboard();
    } catch (e) {
      setError(e.message);
    }
  }

  async function cancelOrder(order) {
    const reason = window.prompt('Reason for cancellation (optional):', 'Customer requested cancellation');
    if (reason === null) return;
    try {
      setError('');
      await request(`/api/orders/${order.id}/cancel`, {
        method: 'POST',
        body: JSON.stringify({ reason: reason.trim() || 'Cancelled by customer' })
      });
      setMessage(`Order #${order.id} was cancelled.`);
      await loadDashboard();
    } catch (e) {
      setError(e.message || 'Failed to cancel order');
    }
  }

  async function download(order) {
    try {
      setError('');
      const res = await request(`/api/orders/${order.id}/download`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = window.document.createElement('a');
      a.style.display = 'none';
      a.href = url;
      a.download = order.original_filename || `order-${order.id}-document`;
      window.document.body.appendChild(a);
      a.click();
      setTimeout(() => {
        window.document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }, 100);
      setMessage(`Downloaded ${order.original_filename || 'document'}.`);
    } catch (e) {
      setError(e.message || 'Download failed');
    }
  }

  async function viewReceipt(order) {
    setError('');
    try {
      const r = await request(`/api/orders/${order.id}/receipt`);
      setReceiptData(r);
    } catch (e) {
      setError(e.message || 'Failed to retrieve receipt');
    }
  }

  async function saveShopPricing(e) {
    e.preventDefault(); setError(''); setMessage('');
    try {
      const updated = await request('/api/shopkeeper/pricing', {
        method: 'PUT',
        body: JSON.stringify({
          bw_price: Number(shop.bw_price),
          color_price: Number(shop.color_price),
          a3_multiplier: Number(shop.a3_multiplier),
          a5_multiplier: Number(shop.a5_multiplier),
          double_sided_discount: Number(shop.double_sided_discount),
          stapling_price: Number(shop.stapling_price)
        })
      });
      setShop(updated);
      setMessage('Shop rates and pricing saved successfully.');
    } catch (e) {
      setError(e.message);
    }
  }

  async function saveShopProfile(e) {
    e.preventDefault(); setError(''); setMessage('');
    try {
      const updated = await request('/api/shopkeeper/shop', {
        method: 'PUT',
        body: JSON.stringify(shop)
      });
      setShop(updated);
      await loadQR();
      setMessage('Shop settings saved successfully.');
    } catch (e) {
      setError(e.message);
    }
  }

  async function downloadQR() {
    try {
      setError('');
      const origin = window.location.origin;
      const res = await request(`/api/shopkeeper/qr?base_url=${encodeURIComponent(origin)}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = window.document.createElement('a');
      a.style.display = 'none';
      a.href = url;
      a.download = `xeroxflow-shop-${shop?.id || 'qr'}.png`;
      window.document.body.appendChild(a);
      a.click();
      setTimeout(() => {
        window.document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }, 100);
      setMessage('Shop QR code downloaded successfully.');
    } catch (e) {
      setError(e.message || 'QR download failed');
    }
  }

  // Filter orders by status, search, and date
  const filteredOrders = useMemo(() => {
    return orders.filter(o => {
      if (orderFilter !== 'all') {
        if (orderFilter === 'active') {
          if (!['pending', 'accepted', 'printing', 'ready'].includes(o.status)) return false;
        } else if (orderFilter === 'cancelled') {
          if (!['cancelled', 'rejected'].includes(o.status)) return false;
        } else if (o.status !== orderFilter) {
          return false;
        }
      }
      if (orderSearch.trim()) {
        const term = orderSearch.trim().toLowerCase();
        const match =
          String(o.id).includes(term) ||
          (o.original_filename && o.original_filename.toLowerCase().includes(term)) ||
          (o.customer_name && o.customer_name.toLowerCase().includes(term)) ||
          (o.shop_name && o.shop_name.toLowerCase().includes(term));
        if (!match) return false;
      }
      if (orderDateRange !== 'all' && o.created_at) {
        const orderDate = new Date(o.created_at);
        const now = new Date();
        if (orderDateRange === 'today') {
          if (orderDate.toDateString() !== now.toDateString()) return false;
        } else if (orderDateRange === 'week') {
          const sevenDaysAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
          if (orderDate < sevenDaysAgo) return false;
        } else if (orderDateRange === 'month') {
          const thirtyDaysAgo = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
          if (orderDate < thirtyDaysAgo) return false;
        }
      }
      return true;
    });
  }, [orders, orderFilter, orderSearch, orderDateRange]);

  if (directShopId) {
    return (
      <div className="direct-upload-shell">
        <DirectUploadPage
          shop={directShop}
          shopId={directShopId}
          loading={directShopLoading}
          error={directShopError}
          user={user}
          onAuthSuccess={(u, s) => {
            setUser(u);
            if (s) setShop(s);
            loadDashboard();
          }}
          onExit={handleExitDirectUpload}
          onViewReceipt={viewReceipt}
          onGoToOrders={() => {
            handleExitDirectUpload();
            setTab('orders');
          }}
        />

        {receiptData && (
          <ReceiptModal
            receiptData={receiptData}
            onClose={() => setReceiptData(null)}
            onPay={() => setShowPayModal(true)}
            onMarkPaid={markPaymentDone}
            user={user}
          />
        )}

        {showPayModal && (
          <PayModal
            receiptData={receiptData}
            onClose={() => setShowPayModal(false)}
          />
        )}
      </div>
    );
  }

  if (!user) {
    return (
      <main className="auth-shell">
        <div className="brand">
          <span className="brand-icon">X</span>
          <span>XeroxFlow <b>SmartPrint</b></span>
        </div>
        <section className="auth-card">
          <div className="eyebrow">SMART PRINTING & ORDER MANAGEMENT</div>
          <h1>{mode === 'login' ? 'Welcome back' : 'Create your account'}</h1>
          <p className="muted">Upload documents, configure print options, track pickups, and manage local printing.</p>
          <div className="role-switch">
            <button className={role === 'customer' ? 'selected' : ''} onClick={() => setRole('customer')}>Customer</button>
            <button className={role === 'shopkeeper' ? 'selected' : ''} onClick={() => setRole('shopkeeper')}>Shopkeeper</button>
          </div>
          <form onSubmit={submitAuth} className="stack">
            {mode === 'register' && (
              <>
                <label>Your name<input required minLength="2" value={form.name} onChange={e => field('name', e.target.value)} placeholder="Full name" /></label>
                <label>Phone number<input required value={form.phone} onChange={e => field('phone', e.target.value)} placeholder="+91..." /></label>
                {role === 'shopkeeper' && (
                  <>
                    <label>Shop name<input required value={form.shop_name} onChange={e => field('shop_name', e.target.value)} placeholder="e.g. Sri Sai Xerox" /></label>
                    <label>Shop address<input required value={form.address} onChange={e => field('address', e.target.value)} placeholder="Street, area, city" /></label>
                  </>
                )}
              </>
            )}
            <label>Email address<input type="email" required value={form.email} onChange={e => field('email', e.target.value)} placeholder="you@example.com" /></label>
            <label>Password<input type="password" required minLength="8" value={form.password} onChange={e => field('password', e.target.value)} placeholder="At least 8 characters" /></label>
            {error && <div className="alert error">{error}</div>}
            {message && <div className="alert success">{message}</div>}
            <button className="primary" disabled={busy}>{busy ? 'Please wait…' : mode === 'login' ? 'Log in securely' : `Create ${role} account`}</button>
          </form>
          <p className="auth-foot">
            {mode === 'login' ? 'New to XeroxFlow?' : 'Already have an account?'} <button className="link" onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(''); }}>{mode === 'login' ? 'Create account' : 'Log in'}</button>
          </p>
          <p className="tiny">Smart Xerox Platform • Automated Pricing, Ordering & Receipts</p>
        </section>
      </main>
    );
  }

  return (
    <div className="app-shell">
      <aside className="sidebar no-print">
        <div className="brand">
          <span className="brand-icon">X</span>
          <span>XeroxFlow <b>SmartPrint</b></span>
        </div>
        <div className="side-label">WORKSPACE</div>
        {(user.role === 'customer'
          ? [
              ['overview', 'Overview'],
              ['new', 'New print order'],
              ['orders', 'My orders'],
              ['shops', 'Find a shop']
            ]
          : [
              ['overview', 'Overview'],
              ['jobs', 'Print jobs'],
              ['pricing', 'Pricing & Rates'],
              ['settings', 'Shop profile']
            ]
        ).map(([id, label]) => (
          <button key={id} className={`nav-item ${tab === id ? 'active' : ''}`} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
        <div className="side-bottom">
          <div className="avatar">{user.name?.slice(0, 1).toUpperCase()}</div>
          <div className="user-meta">
            <b>{user.name}</b>
            <small>{user.role}</small>
          </div>
          <button className="logout" onClick={logout} title="Log out">↗</button>
        </div>
      </aside>

      <main className="main">
        <header className="topbar no-print">
          <div>
            <div className="eyebrow">{user.role === 'customer' ? 'CUSTOMER PORTAL' : 'SHOP MANAGEMENT'}</div>
            <h1>
              {tab === 'overview' ? 'Overview'
                : tab === 'new' ? 'New print order'
                : tab === 'orders' ? 'My orders'
                : tab === 'shops' ? 'Available print shops'
                : tab === 'jobs' ? 'Print jobs & management'
                : tab === 'pricing' ? 'Shop pricing & rates'
                : 'Shop settings'}
            </h1>
          </div>
          <div className="top-actions">
            {user.role === 'customer' && (
              <button
                className="primary small"
                onClick={() => setShowScanner(true)}
                style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontWeight: 700 }}
              >
                📷 Scan QR
              </button>
            )}
            <span className="online-dot">● System Active</span>
            <button className="secondary small" onClick={refresh}>↻ Refresh</button>
          </div>
        </header>

        {error && (
          <div className="alert error global-alert no-print">
            {error}
            <button onClick={() => setError('')}>×</button>
          </div>
        )}
        {message && (
          <div className="alert success global-alert no-print">
            {message}
            <button onClick={() => setMessage('')}>×</button>
          </div>
        )}

        {/* OVERVIEW TAB */}
        {tab === 'overview' && (
          <>
            <section className="welcome no-print">
              <div>
                <span className="welcome-pill">✦ Smart Printing Platform</span>
                <h2>{user.role === 'customer' ? 'Print smarter. Skip the queue.' : `Welcome back, ${shop?.name || user.name}`}</h2>
                <p>
                  {user.role === 'customer'
                    ? 'Upload PDF/documents, choose precise print specifications, and track order progress.'
                    : 'Manage incoming print orders, automate itemized pricing, and issue digital receipts.'}
                </p>
              </div>
              <div className="welcome-art">▤<span>✓</span></div>
            </section>

            <div className="stats-grid no-print">
              <Stat label={user.role === 'customer' ? 'Total orders' : 'Total jobs'} value={orders.length} icon="▤" />
              <Stat label="Pending / New" value={orders.filter(o => o.status === 'pending').length} icon="◷" />
              <Stat label="Ready for pickup" value={orders.filter(o => o.status === 'ready').length} icon="✓" />
            </div>

            {user.role === 'customer' ? (
              <section className="panel no-print">
                <div className="panel-head">
                  <div>
                    <h3>Quick actions</h3>
                    <p>Scan a counter QR code or configure an order with real-time pricing.</p>
                  </div>
                  <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                    <button
                      className="primary"
                      onClick={() => setShowScanner(true)}
                      style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', fontWeight: 700 }}
                    >
                      📷 Scan Shop QR
                    </button>
                    <button className="secondary" onClick={() => setTab('new')}>
                      + New print order
                    </button>
                  </div>
                </div>
                <ol className="steps">
                  <li><b>1. Scan QR or Select Shop</b><span>Scan counter QR code to upload directly, or choose your shop.</span></li>
                  <li><b>2. Upload Document & Specs</b><span>PDF pages are automatically extracted & validated against page ranges.</span></li>
                  <li><b>3. Track & Pick Up</b><span>Follow real-time status and pay at the shop counter upon pickup.</span></li>
                </ol>
              </section>
            ) : (
              <section className="panel no-print">
                <div className="panel-head">
                  <div>
                    <h3>Your shop counter QR code</h3>
                    <p>Customers can scan this QR code with their mobile phone to open your order form directly.</p>
                  </div>
                  <button className="primary" onClick={downloadQR} disabled={qrLoading}>
                    {qrLoading ? 'Generating QR…' : 'Download QR PNG'}
                  </button>
                </div>
                {qrError ? (
                  <div className="alert error">{qrError} <button className="link" onClick={loadQR} style={{ marginLeft: 8 }}>Retry</button></div>
                ) : qrLoading ? (
                  <p className="muted">Loading shop QR code preview…</p>
                ) : qrBlobUrl ? (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '20px', flexWrap: 'wrap' }}>
                    <img
                      src={qrBlobUrl}
                      alt={`${shop?.name || 'Shop'} QR Code`}
                      style={{ width: '140px', height: '140px', borderRadius: '10px', border: '1px solid #dce3ed', background: '#fff', padding: '6px' }}
                    />
                    <div style={{ flex: 1, minWidth: '220px' }}>
                      <div style={{ fontSize: '12px', fontWeight: 700, color: '#32445d', marginBottom: '6px' }}>Mobile Scanning Link:</div>
                      <div style={{ fontSize: '12px', wordBreak: 'break-all', color: '#2864d7', background: '#edf3ff', padding: '8px 12px', borderRadius: '8px', marginBottom: '8px' }}>
                        <a href={qrTargetUrl || '#'} target="_blank" rel="noreferrer" style={{ color: 'inherit', textDecoration: 'none' }}>
                          {qrTargetUrl || 'Loading target link…'}
                        </a>
                      </div>
                      <p className="muted" style={{ margin: 0, fontSize: '11px', lineHeight: 1.5 }}>
                        Customers scanning this QR on local Wi-Fi or production connect directly to your shop.
                      </p>
                    </div>
                  </div>
                ) : (
                  <p className="muted">QR preview unavailable. Click refresh or retry.</p>
                )}
              </section>
            )}

            <div className="panel no-print">
              <div className="panel-head">
                <div>
                  <h3>Recent orders</h3>
                  <p>Latest active jobs and submissions.</p>
                </div>
                {user.role === 'customer' ? (
                  <button className="secondary small" onClick={() => setTab('orders')}>View all orders →</button>
                ) : (
                  <button className="secondary small" onClick={() => setTab('jobs')}>Go to job manager →</button>
                )}
              </div>
              <OrderList
                orders={orders.slice(0, 4)}
                shopkeeper={user.role === 'shopkeeper'}
                onDownload={download}
                onSelectOrder={setSelectedOrder}
                onReceipt={viewReceipt}
                onCancel={cancelOrder}
                onMarkPaid={markPaymentDone}
              />
            </div>
          </>
        )}

        {/* FEATURE 1: ADVANCED PRINT-ORDER FORM (CUSTOMER) */}
        {tab === 'new' && user.role === 'customer' && (
          <section className="panel no-print">
            <div className="panel-head">
              <div>
                <h3>Configure print order</h3>
                <p>Customize printing mode, paper, sides, orientation, and finishing with automated instant pricing.</p>
              </div>
            </div>

            <div style={{
              background: '#edf3ff',
              border: '1px solid #d4e4fd',
              borderRadius: '12px',
              padding: '12px 16px',
              marginBottom: '16px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: '12px',
              flexWrap: 'wrap'
            }}>
              <div>
                <b style={{ color: '#183b73', fontSize: '13px' }}>📱 Standing at a Xerox counter?</b>
                <div style={{ color: '#56677f', fontSize: '12px', marginTop: '2px' }}>
                  Scan the shop counter QR code to upload your document directly without manual configuration.
                </div>
              </div>
              <button
                type="button"
                className="primary small"
                onClick={() => setShowScanner(true)}
                style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', whiteSpace: 'nowrap', fontWeight: 700 }}
              >
                📷 Scan Counter QR
              </button>
            </div>

            <form className="stack" onSubmit={createOrder}>
              <label>
                Choose Xerox shop
                <select
                  required
                  value={orderForm.shop_id}
                  onChange={e => setOrderForm({ ...orderForm, shop_id: e.target.value })}
                >
                  <option value="">Select a print shop</option>
                  {shops.map(s => (
                    <option value={s.id} key={s.id}>
                      {s.name} — B/W {money(s.bw_price)}/pg | Colour {money(s.color_price)}/pg
                    </option>
                  ))}
                </select>
              </label>

              <label>
                Document (PDF, TXT, DOC/DOCX, JPG, PNG)
                <input
                  id="file-upload-input"
                  required
                  type="file"
                  accept=".pdf,.txt,.doc,.docx,.jpg,.jpeg,.png"
                  onChange={e => setUploadFile(e.target.files?.[0] || null)}
                />
                {uploadFile && (
                  <div style={{ fontSize: '11px', color: '#16764a', marginTop: '4px' }}>
                    ✓ Selected: <b>{uploadFile.name}</b> ({(uploadFile.size / 1024).toFixed(1)} KB)
                  </div>
                )}
              </label>

              <div className="form-grid">
                <label>
                  Printing mode
                  <select
                    value={orderForm.color_mode}
                    onChange={e => setOrderForm({ ...orderForm, color_mode: e.target.value })}
                  >
                    <option value="bw">Black & White</option>
                    <option value="color">Colour</option>
                  </select>
                </label>

                <label>
                  Number of copies
                  <input
                    type="number"
                    min="1"
                    max="500"
                    required
                    value={orderForm.copies}
                    onChange={e => setOrderForm({ ...orderForm, copies: e.target.value })}
                  />
                </label>

                <label>
                  Pages to print
                  <input
                    value={orderForm.pages}
                    onChange={e => setOrderForm({ ...orderForm, pages: e.target.value })}
                    placeholder="all, or e.g. 1-5, 1,3,5"
                  />
                  <span style={{ fontSize: '10px', color: '#7a8a9e' }}>Use 'all', a page count, or ranges like 1-5</span>
                </label>

                <label>
                  Paper size
                  <select
                    value={orderForm.paper_size}
                    onChange={e => setOrderForm({ ...orderForm, paper_size: e.target.value })}
                  >
                    <option value="A4">A4 (Standard)</option>
                    <option value="A3">A3 (Large poster/sheet)</option>
                    <option value="A5">A5 (Compact booklet)</option>
                  </select>
                </label>

                <label>
                  Print sides
                  <select
                    value={orderForm.sides}
                    onChange={e => setOrderForm({ ...orderForm, sides: e.target.value })}
                  >
                    <option value="single">Single-sided (1 page per sheet)</option>
                    <option value="double">Double-sided (Duplex, 2 pages per sheet)</option>
                  </select>
                </label>

                <label>
                  Page orientation
                  <select
                    value={orderForm.orientation}
                    onChange={e => setOrderForm({ ...orderForm, orientation: e.target.value })}
                  >
                    <option value="portrait">Portrait</option>
                    <option value="landscape">Landscape</option>
                  </select>
                </label>

                <label>
                  Finishing option
                  <select
                    value={orderForm.finishing}
                    onChange={e => setOrderForm({ ...orderForm, finishing: e.target.value })}
                  >
                    <option value="none">None</option>
                    <option value="stapling">Stapling (top-left corner)</option>
                  </select>
                </label>
              </div>

              <label>
                Instructions for the shopkeeper (optional)
                <textarea
                  rows="2"
                  value={orderForm.notes}
                  onChange={e => setOrderForm({ ...orderForm, notes: e.target.value })}
                  placeholder="e.g. Spiral binding required, urgent for exam, use thicker paper if available…"
                />
              </label>

              {/* Real-time automated price breakdown card */}
              {liveEstimate && (
                <div className="price-breakdown-card">
                  <div className="breakdown-title">Automated Price Breakdown</div>
                  <div className="breakdown-row">
                    <span>Base rate ({liveEstimate.color_mode === 'color' ? 'Colour' : 'B/W'}, {liveEstimate.paper_size}):</span>
                    <b>{money(liveEstimate.effective_page_rate)}/page</b>
                  </div>
                  <div className="breakdown-row">
                    <span>Pages selected:</span>
                    <span>{liveEstimate.selected_page_count} pages ({liveEstimate.sheets_per_copy} sheets/copy)</span>
                  </div>
                  {liveEstimate.double_sided_discount_percent > 0 && liveEstimate.sides === 'double' && (
                    <div className="breakdown-row">
                      <span>Double-side discount:</span>
                      <span style={{ color: '#18834f' }}>-{liveEstimate.double_sided_discount_percent}%</span>
                    </div>
                  )}
                  <div className="breakdown-row">
                    <span>Printing cost ({liveEstimate.copies} {liveEstimate.copies === 1 ? 'copy' : 'copies'}):</span>
                    <b>{money(liveEstimate.total_printing_cost)}</b>
                  </div>
                  {liveEstimate.finishing === 'stapling' && (
                    <div className="breakdown-row">
                      <span>Stapling charge ({liveEstimate.copies} sets):</span>
                      <b>{money(liveEstimate.total_finishing_cost)}</b>
                    </div>
                  )}
                  <div className="breakdown-row total">
                    <span>Estimated Total:</span>
                    <span style={{ color: '#2864d7' }}>{money(liveEstimate.subtotal)}</span>
                  </div>
                  {liveEstimate.requires_quote ? (
                    <div className="breakdown-note" style={{ color: '#a8740c' }}>
                      ⚠ {liveEstimate.quote_reason || 'This document requires shopkeeper manual quote upon receipt.'}
                    </div>
                  ) : (
                    <div className="breakdown-note">
                      ✓ Calculated dynamically using {shops.find(s => String(s.id) === String(orderForm.shop_id))?.name || 'shop'}'s verified rates.
                    </div>
                  )}
                </div>
              )}

              <button className="primary" disabled={busy || estimating}>
                {busy ? 'Submitting Order…' : 'Submit print order →'}
              </button>
            </form>
          </section>
        )}

        {/* FEATURE 4: CUSTOMER ORDER TRACKING */}
        {tab === 'orders' && user.role === 'customer' && (
          <section className="panel no-print">
            <div className="panel-head">
              <div>
                <h3>Order history & tracking</h3>
                <p>Track order progress, download receipts, and manage submissions.</p>
              </div>
              <button className="primary" onClick={() => setTab('new')}>+ New order</button>
            </div>

            <div className="filters-bar">
              <div className="pills-group">
                {['all', 'active', 'completed', 'cancelled'].map(f => (
                  <button
                    key={f}
                    className={`pill-btn ${orderFilter === f ? 'active' : ''}`}
                    onClick={() => setOrderFilter(f)}
                  >
                    {f.charAt(0).toUpperCase() + f.slice(1)}
                  </button>
                ))}
              </div>
              <div className="filter-inputs">
                <input
                  type="text"
                  placeholder="Search by order ID, filename…"
                  className="filter-search"
                  value={orderSearch}
                  onChange={e => setOrderSearch(e.target.value)}
                />
              </div>
            </div>

            <OrderList
              orders={filteredOrders}
              shopkeeper={false}
              onDownload={download}
              onSelectOrder={setSelectedOrder}
              onReceipt={viewReceipt}
              onCancel={cancelOrder}
              onMarkPaid={markPaymentDone}
            />
          </section>
        )}

        {/* FEATURE 3: SHOPKEEPER ORDER MANAGEMENT */}
        {tab === 'jobs' && user.role === 'shopkeeper' && (
          <section className="panel no-print">
            <div className="panel-head">
              <div>
                <h3>Print job management</h3>
                <p>Filter by status, search orders, execute validated state transitions, and track payments.</p>
              </div>
            </div>

            <div className="filters-bar">
              <div className="pills-group">
                {[
                  ['all', 'All'],
                  ['pending', 'New Pending'],
                  ['accepted', 'Accepted'],
                  ['printing', 'Printing'],
                  ['ready', 'Ready for pickup'],
                  ['completed', 'Completed'],
                  ['cancelled', 'Cancelled']
                ].map(([val, label]) => (
                  <button
                    key={val}
                    className={`pill-btn ${orderFilter === val ? 'active' : ''}`}
                    onClick={() => setOrderFilter(val)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="filter-inputs">
                <input
                  type="text"
                  placeholder="Search order #, customer, file…"
                  className="filter-search"
                  value={orderSearch}
                  onChange={e => setOrderSearch(e.target.value)}
                />
                <select
                  className="filter-select"
                  value={orderDateRange}
                  onChange={e => setOrderDateRange(e.target.value)}
                >
                  <option value="all">All Dates</option>
                  <option value="today">Today</option>
                  <option value="week">Last 7 Days</option>
                  <option value="month">Last 30 Days</option>
                </select>
              </div>
            </div>

            <OrderList
              orders={filteredOrders}
              shopkeeper={true}
              onDownload={download}
              onSelectOrder={setSelectedOrder}
              onReceipt={viewReceipt}
              onCancel={cancelOrder}
              onMarkPaid={markPaymentDone}
            />
          </section>
        )}

        {/* FEATURE 2: SHOPKEEPER PRICING CONFIGURATION */}
        {tab === 'pricing' && user.role === 'shopkeeper' && shop && (
          <section className="panel no-print">
            <div className="panel-head">
              <div>
                <h3>Shop pricing & rates</h3>
                <p>Configure page rates, multipliers, double-sided discounts, and finishing fees. Stored in database.</p>
              </div>
            </div>
            <form className="stack" onSubmit={saveShopPricing}>
              <div className="form-grid">
                <label>
                  Black & White price per page (₹)
                  <input
                    type="number"
                    min="0"
                    step="0.5"
                    required
                    value={shop.bw_price}
                    onChange={e => setShop({ ...shop, bw_price: e.target.value })}
                  />
                  <span style={{ fontSize: '10px', color: '#7a8a9e' }}>Base rate for standard A4 B/W print</span>
                </label>

                <label>
                  Colour price per page (₹)
                  <input
                    type="number"
                    min="0"
                    step="0.5"
                    required
                    value={shop.color_price}
                    onChange={e => setShop({ ...shop, color_price: e.target.value })}
                  />
                  <span style={{ fontSize: '10px', color: '#7a8a9e' }}>Base rate for standard A4 Colour print</span>
                </label>

                <label>
                  A3 paper multiplier (ratio)
                  <input
                    type="number"
                    min="0.5"
                    max="10"
                    step="0.1"
                    required
                    value={shop.a3_multiplier || 2.0}
                    onChange={e => setShop({ ...shop, a3_multiplier: e.target.value })}
                  />
                  <span style={{ fontSize: '10px', color: '#7a8a9e' }}>e.g. 2.0 = double standard A4 price</span>
                </label>

                <label>
                  A5 paper multiplier (ratio)
                  <input
                    type="number"
                    min="0.1"
                    max="5"
                    step="0.1"
                    required
                    value={shop.a5_multiplier || 0.8}
                    onChange={e => setShop({ ...shop, a5_multiplier: e.target.value })}
                  />
                  <span style={{ fontSize: '10px', color: '#7a8a9e' }}>e.g. 0.8 = 20% cheaper than A4</span>
                </label>

                <label>
                  Double-sided discount (%)
                  <input
                    type="number"
                    min="0"
                    max="100"
                    step="1"
                    required
                    value={shop.double_sided_discount || 0}
                    onChange={e => setShop({ ...shop, double_sided_discount: e.target.value })}
                  />
                  <span style={{ fontSize: '10px', color: '#7a8a9e' }}>Percentage discount applied when printing duplex</span>
                </label>

                <label>
                  Stapling charge per set (₹)
                  <input
                    type="number"
                    min="0"
                    step="1"
                    required
                    value={shop.stapling_price || 5.0}
                    onChange={e => setShop({ ...shop, stapling_price: e.target.value })}
                  />
                  <span style={{ fontSize: '10px', color: '#7a8a9e' }}>Flat finishing fee per copy set</span>
                </label>
              </div>
              <button className="primary" style={{ alignSelf: 'flex-start' }}>Save pricing configuration</button>
            </form>
          </section>
        )}

        {/* CUSTOMER FIND SHOPS */}
        {tab === 'shops' && user.role === 'customer' && (
          <section className="panel no-print">
            <div className="panel-head">
              <div>
                <h3>Available Xerox shops</h3>
                <p>Select a shop to begin your order with transparent pricing.</p>
              </div>
            </div>
            <div className="shop-grid">
              {shops.map(s => (
                <div className="shop-card" key={s.id}>
                  <div className="shop-icon">▣</div>
                  <h3>{s.name}</h3>
                  <p>{s.address}</p>
                  <div className="price-line"><span>B/W per page</span><b>{money(s.bw_price)}</b></div>
                  <div className="price-line"><span>Color per page</span><b>{money(s.color_price)}</b></div>
                  <div className="price-line"><span>Duplex discount</span><b>{s.double_sided_discount || 0}%</b></div>
                  <button
                    className="primary full"
                    onClick={() => {
                      setOrderForm({ ...orderForm, shop_id: String(s.id) });
                      setTab('new');
                    }}
                  >
                    Order here →
                  </button>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* SHOP SETTINGS */}
        {tab === 'settings' && user.role === 'shopkeeper' && shop && (
          <section className="panel no-print">
            <div className="panel-head">
              <div>
                <h3>Shop profile & details</h3>
                <p>Manage contact info, location address, and counter QR codes.</p>
              </div>
            </div>
            <form className="stack" onSubmit={saveShopProfile}>
              <label>Shop name<input required value={shop.name} onChange={e => setShop({ ...shop, name: e.target.value })} /></label>
              <label>Address<input required value={shop.address} onChange={e => setShop({ ...shop, address: e.target.value })} /></label>
              <label>Phone<input required value={shop.phone} onChange={e => setShop({ ...shop, phone: e.target.value })} /></label>
              <div style={{ display: 'flex', gap: '10px', marginTop: '10px' }}>
                <button className="primary">Save profile</button>
                <button type="button" className="secondary" onClick={downloadQR}>Download shop QR code</button>
              </div>
            </form>
          </section>
        )}

        <footer className="no-print">
          © 2026 XeroxFlow SmartPrint <span>Phase 2: Smart Order Management, Pricing & Billing</span>
        </footer>
      </main>

      {/* MODAL: ORDER DETAILS & SHOPKEEPER ACTIONS */}
      {selectedOrder && (
        <div className="modal-overlay no-print" onClick={() => setSelectedOrder(null)}>
          <div className="modal-box" onClick={e => e.stopPropagation()}>
            <div className="modal-head">
              <h3>
                {user?.role === 'shopkeeper'
                  ? `${((selectedOrder.customer_name && selectedOrder.customer_name.trim()) || 'Customer')} · Order #${selectedOrder.id}`
                  : `Order #${selectedOrder.id} Details`}
              </h3>
              <button className="modal-close" onClick={() => setSelectedOrder(null)}>×</button>
            </div>
            <div className="modal-body stack">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span className={`status status-${selectedOrder.status}`}>
                  Status: {selectedOrder.status.replace('_', ' ')}
                </span>
                <span className={`badge-payment ${selectedOrder.payment_status || 'pending'}`}>
                  Payment: {selectedOrder.payment_status || 'pending'}
                </span>
              </div>

              {/* Status Timeline */}
              <OrderTimeline status={selectedOrder.status} />

              <div style={{ background: '#f5f7fb', padding: '14px', borderRadius: '10px', fontSize: '12px' }}>
                <div><b>Customer:</b> {((selectedOrder.customer_name && selectedOrder.customer_name.trim()) || 'Customer')} {selectedOrder.customer_phone ? `(${selectedOrder.customer_phone})` : ''} {selectedOrder.customer_email ? `· ${selectedOrder.customer_email}` : ''}</div>
                <div style={{ marginTop: '4px' }}><b>File:</b> {selectedOrder.original_filename || 'No document'}</div>
                <div style={{ marginTop: '4px' }}><b>Shop:</b> {selectedOrder.shop_name} ({selectedOrder.shop_phone})</div>
                <div style={{ marginTop: '4px' }}><b>Submitted:</b> {new Date(selectedOrder.created_at).toLocaleString()}</div>
                {selectedOrder.cancellation_reason && (
                  <div style={{ marginTop: '6px', color: '#b3343c' }}><b>Cancellation note:</b> {selectedOrder.cancellation_reason}</div>
                )}
                {selectedOrder.rejection_reason && (
                  <div style={{ marginTop: '6px', color: '#b3343c' }}><b>Rejection note:</b> {selectedOrder.rejection_reason}</div>
                )}
              </div>

              <div style={{ fontSize: '12px' }}>
                <h4 style={{ margin: '8px 0', fontSize: '13px' }}>Print Specifications</h4>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', background: '#fff', border: '1px solid #edf1f7', padding: '12px', borderRadius: '8px' }}>
                  <div><b>Document:</b> {selectedOrder.original_filename}</div>
                  <div><b>Copies:</b> {selectedOrder.copies}</div>
                  <div><b>Color mode:</b> {selectedOrder.color_mode === 'color' ? 'Colour' : 'Black & White'}</div>
                  <div><b>Paper size:</b> {selectedOrder.paper_size}</div>
                  <div><b>Sides:</b> {selectedOrder.sides === 'double' ? 'Double-sided' : 'Single-sided'}</div>
                  <div><b>Orientation:</b> {(selectedOrder.orientation || 'portrait').toUpperCase()}</div>
                  <div><b>Finishing:</b> {selectedOrder.finishing === 'stapling' ? 'Stapling' : 'None'}</div>
                  <div><b>Pages:</b> {selectedOrder.pages} ({selectedOrder.page_count} pgs, {selectedOrder.sheets_count} sheets)</div>
                </div>
                {selectedOrder.notes && (
                  <div style={{ marginTop: '8px', padding: '8px 12px', background: '#fff8e6', borderRadius: '6px', fontSize: '11px', color: '#875d04' }}>
                    <b>Customer notes:</b> {selectedOrder.notes}
                  </div>
                )}
              </div>

              {/* Price Breakdown Snapshot */}
              {selectedOrder.price_breakdown && (
                <div className="price-breakdown-card" style={{ margin: '4px 0' }}>
                  <div className="breakdown-title">Itemized Pricing Snapshot</div>
                  <div className="breakdown-row">
                    <span>Base rate ({selectedOrder.price_breakdown.color_mode}, {selectedOrder.price_breakdown.paper_size}):</span>
                    <b>{money(selectedOrder.price_breakdown.effective_page_rate || selectedOrder.price_breakdown.rate_per_page || selectedOrder.price_breakdown.base_page_rate)}/pg</b>
                  </div>
                  <div className="breakdown-row">
                    <span>Printing cost ({selectedOrder.copies} {selectedOrder.copies === 1 ? 'copy' : 'copies'} · {selectedOrder.price_breakdown.billable_page_count || selectedOrder.page_count} pgs):</span>
                    <b>{selectedOrder.requires_quote ? 'Awaiting quotation' : money(selectedOrder.price_breakdown.total_printing_cost)}</b>
                  </div>
                  {selectedOrder.price_breakdown.total_finishing_cost > 0 && (
                    <div className="breakdown-row">
                      <span>Finishing (Stapling):</span>
                      <b>{money(selectedOrder.price_breakdown.total_finishing_cost)}</b>
                    </div>
                  )}
                  <div className="breakdown-row total">
                    <span>Final Total:</span>
                    <b style={{ color: selectedOrder.requires_quote ? '#b37400' : '#2864d7' }}>
                      {selectedOrder.requires_quote ? 'Awaiting quotation' : money(selectedOrder.final_price || selectedOrder.estimated_price)}
                    </b>
                  </div>
                </div>
              )}

              {/* Shopkeeper Actions: Payment Status, Quote, Status Transitions */}
              {user.role === 'shopkeeper' && (
                <div style={{ borderTop: '1px solid #edf1f7', paddingTop: '12px' }}>
                  <h4 style={{ margin: '6px 0 10px', fontSize: '13px' }}>Shopkeeper Workflow Actions</h4>

                  {/* Prominent Payment Section */}
                  <div style={{
                    background: selectedOrder.payment_status === 'paid' ? '#f0fbf4' : '#fff9ec',
                    border: `1px solid ${selectedOrder.payment_status === 'paid' ? '#bcebc8' : '#fce3a8'}`,
                    padding: '12px 14px',
                    borderRadius: '9px',
                    marginBottom: '12px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: '12px'
                  }}>
                    <div>
                      <div style={{ fontSize: '12px', fontWeight: 800, color: selectedOrder.payment_status === 'paid' ? '#146c3b' : '#926006' }}>
                        Payment Status: {selectedOrder.payment_status.toUpperCase()}
                      </div>
                      <div style={{ fontSize: '11px', color: '#68778d', marginTop: '2px' }}>
                        {selectedOrder.payment_status === 'paid'
                          ? `Payment recorded as PAID${selectedOrder.paid_at ? ` on ${new Date(selectedOrder.paid_at).toLocaleString()}` : ''}`
                          : `Amount to collect: ${selectedOrder.requires_quote ? 'Awaiting quotation' : money(selectedOrder.final_price || selectedOrder.estimated_price)}`}
                      </div>
                    </div>
                    {selectedOrder.payment_status === 'pending' ? (
                      <button
                        className="primary small"
                        style={{ background: '#0d7d3c', whiteSpace: 'nowrap' }}
                        onClick={() => markPaymentDone(selectedOrder)}
                      >
                        ✓ Payment Done
                      </button>
                    ) : (
                      <span className="badge-payment paid">PAID</span>
                    )}
                  </div>

                  {/* Manual Quotation if requires_quote */}
                  {selectedOrder.requires_quote && !['completed', 'rejected', 'cancelled'].includes(selectedOrder.status) && (
                    <div style={{ background: '#fdf7ea', padding: '12px', borderRadius: '8px', marginBottom: '12px' }}>
                      <div style={{ fontSize: '12px', fontWeight: 700, color: '#8c6004', marginBottom: '6px' }}>Manual Quotation Required</div>
                      <div style={{ display: 'flex', gap: '8px' }}>
                        <input
                          type="number"
                          placeholder="Enter total quote in ₹"
                          style={{ padding: '8px', fontSize: '12px', width: '180px' }}
                          value={quoteInput}
                          onChange={e => setQuoteInput(e.target.value)}
                        />
                        <button
                          className="primary small"
                          disabled={!quoteInput}
                          onClick={() => {
                            changeStatus(selectedOrder, 'accepted', 'Quotation provided by shopkeeper', Number(quoteInput));
                            setQuoteInput('');
                          }}
                        >
                          Accept & Set Quote
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Status transitions based on server rules */}
                  {!['completed', 'rejected', 'cancelled'].includes(selectedOrder.status) && (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '12px' }}>
                      {selectedOrder.status === 'pending' && (
                        <>
                          <button className="primary small" onClick={() => changeStatus(selectedOrder, 'accepted')}>✓ Accept Order</button>
                          <button
                            className="secondary small"
                            style={{ color: '#b3343c' }}
                            onClick={() => {
                              const r = window.prompt('Reason for rejection:');
                              if (r !== null) changeStatus(selectedOrder, 'rejected', r || 'Rejected by shop');
                            }}
                          >
                            ✕ Reject Order
                          </button>
                        </>
                      )}
                      {selectedOrder.status === 'accepted' && (
                        <button className="primary small" onClick={() => changeStatus(selectedOrder, 'printing')}>▶ Start Printing</button>
                      )}
                      {selectedOrder.status === 'printing' && (
                        <button className="primary small" onClick={() => changeStatus(selectedOrder, 'ready')}>✓ Mark Ready for Pickup</button>
                      )}
                      {selectedOrder.status === 'ready' && (
                        <button className="primary small" onClick={() => changeStatus(selectedOrder, 'completed')}>★ Mark Completed</button>
                      )}
                      {['pending', 'accepted', 'printing'].includes(selectedOrder.status) && (
                        <button
                          className="secondary small"
                          onClick={() => {
                            const r = window.prompt('Reason for cancellation:');
                            if (r !== null) changeStatus(selectedOrder, 'cancelled', r || 'Shop cancelled order');
                          }}
                        >
                          Cancel Job
                        </button>
                      )}
                    </div>
                  )}

                  {/* Payment status control pills */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <span style={{ fontSize: '11px', fontWeight: 700 }}>Update Payment:</span>
                    {['pending', 'paid', 'refunded'].map(ps => (
                      <button
                        key={ps}
                        className={`pill-btn ${selectedOrder.payment_status === ps ? 'active' : ''}`}
                        onClick={() => updatePaymentStatus(selectedOrder, ps)}
                      >
                        {ps.toUpperCase()}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="modal-foot">
              <button className="secondary" onClick={() => download(selectedOrder)}>Download Document</button>
              <button className="primary" onClick={() => { viewReceipt(selectedOrder); }}>View Receipt</button>
            </div>
          </div>
        </div>
      )}

      {/* FEATURE 5: MODAL: PRINTABLE RECEIPT */}
      {receiptData && (
        <ReceiptModal
          receiptData={receiptData}
          onClose={() => setReceiptData(null)}
          onPay={() => setShowPayModal(true)}
          onMarkPaid={markPaymentDone}
          user={user}
        />
      )}

      {/* BUG 3: MODAL: ONLINE PAYMENT COMING SOON */}
      {showPayModal && (
        <PayModal
          receiptData={receiptData}
          onClose={() => setShowPayModal(false)}
        />
      )}

      {/* PHASE 3: QR SCANNER MODAL */}
      <QrScannerModal
        isOpen={showScanner}
        onClose={() => setShowScanner(false)}
        onSuccess={handleScannerSuccess}
        shops={shops}
      />
    </div>
  );
}

function Stat({ label, value, icon }) {
  return (
    <div className="stat-card">
      <div className="stat-icon">{icon}</div>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
      </div>
    </div>
  );
}

function OrderTimeline({ status }) {
  const isCancelled = ['cancelled', 'rejected'].includes(status);
  const steps = ['pending', 'accepted', 'printing', 'ready', 'completed'];
  const currentIndex = steps.indexOf(status);

  if (isCancelled) {
    return (
      <div className="timeline-track">
        <div className="timeline-step completed">
          <div className="timeline-circle">1</div>
          <div className="timeline-label">Submitted</div>
        </div>
        <div className="timeline-step cancelled">
          <div className="timeline-circle">✕</div>
          <div className="timeline-label">{status.toUpperCase()}</div>
        </div>
      </div>
    );
  }

  return (
    <div className="timeline-track">
      {[
        ['pending', 'Submitted'],
        ['accepted', 'Accepted'],
        ['printing', 'Printing'],
        ['ready', 'Ready'],
        ['completed', 'Picked up']
      ].map(([st, label], idx) => {
        const isDone = currentIndex > idx;
        const isCurrent = currentIndex === idx;
        return (
          <div key={st} className={`timeline-step ${isDone ? 'completed' : ''} ${isCurrent ? 'current' : ''}`}>
            <div className="timeline-circle">{isDone ? '✓' : idx + 1}</div>
            <div className="timeline-label">{label}</div>
          </div>
        );
      })}
    </div>
  );
}

function OrderList({ orders, shopkeeper, onDownload, onSelectOrder, onReceipt, onCancel, onMarkPaid }) {
  if (!orders.length) {
    return (
      <div className="empty">
        <div>▤</div>
        <b>No orders match your filter</b>
        <p>Submitted print orders will appear here.</p>
      </div>
    );
  }

  return (
    <div className="order-list">
      {orders.map(o => (
        <article className="order-row" key={o.id}>
          <div className="file-icon" style={{ fontSize: '9px', fontWeight: 800 }}>
            {o.paper_size || 'DOC'}
          </div>

          <div className="order-info">
            <div className="order-title">
              {shopkeeper ? (
                <span className="order-title-prioritized">
                  <b>{((o.customer_name && o.customer_name.trim()) || 'Customer')}</b> · Order #{o.id}
                </span>
              ) : (
                <span>Order #{o.id} · {o.original_filename || 'No document'}</span>
              )}
            </div>

            {shopkeeper && (
              <div className="order-file-subtitle">
                File: <span>{o.original_filename || 'No document'}</span>
              </div>
            )}

            <div className="order-meta">
              {shopkeeper ? (
                <span><b>Phone:</b> {o.customer_phone || 'Not provided'}</span>
              ) : (
                <span><b>Shop:</b> {o.shop_name}</span>
              )}
              {' · '}
              <span>
                {o.color_mode === 'bw' ? 'B/W' : 'Colour'} · {o.copies} {o.copies === 1 ? 'copy' : 'copies'} · {o.sides} · {o.paper_size || 'A4'}
                {o.finishing === 'stapling' ? ' · Stapled' : ''}
              </span>
              {' · '}
              <span>{new Date(o.created_at).toLocaleDateString()}</span>
            </div>

            <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginTop: '4px' }}>
              <span className={`status status-${o.status}`}>
                {o.status.replace('_', ' ')}
              </span>
              <span className={`badge-payment ${o.payment_status || 'pending'}`}>
                {o.payment_status || 'pending'}
              </span>
              {o.requires_quote && (
                <span style={{ fontSize: '10px', color: '#a8740c', background: '#fff8e6', padding: '2px 6px', borderRadius: '4px' }}>
                  Quote Pending
                </span>
              )}
            </div>
          </div>

          <div className="order-right">
            <b>{o.requires_quote ? 'Quote Pending' : money(o.final_price || o.estimated_price)}</b>
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
              {shopkeeper && o.payment_status === 'pending' && onMarkPaid && (
                <button
                  className="text-button"
                  style={{ color: '#0d7d3c', fontWeight: 800 }}
                  onClick={() => onMarkPaid(o)}
                >
                  ✓ Payment Done
                </button>
              )}
              <button className="text-button" onClick={() => onSelectOrder(o)}>
                Details
              </button>
              <button className="text-button" onClick={() => onReceipt(o)}>
                Receipt
              </button>
              {o.original_filename ? (
                <button className="text-button" onClick={() => onDownload(o)}>
                  File
                </button>
              ) : null}
              {!shopkeeper && o.status === 'pending' && (
                <button
                  className="text-button"
                  style={{ color: '#b3343c' }}
                  onClick={() => onCancel(o)}
                >
                  Cancel
                </button>
              )}
            </div>
          </div>
        </article>
      ))}
    </div>
  );
}

function ReceiptModal({ receiptData, onClose, onPay, onMarkPaid, user }) {
  if (!receiptData) return null;
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box printable-receipt" onClick={e => e.stopPropagation()} style={{ maxWidth: '680px' }}>
        <div className="modal-head no-print">
          <h3>Official Print Order Receipt</h3>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>

        <div className="modal-body">
          <div className="receipt-paper">
            <div className="receipt-brand">
              <div>
                <h2 style={{ margin: '0 0 4px', fontSize: '20px', fontFamily: 'Manrope, sans-serif' }}>{receiptData.shop.name}</h2>
                <div style={{ fontSize: '11px', color: '#6e8096' }}>{receiptData.shop.address}</div>
                <div style={{ fontSize: '11px', color: '#6e8096' }}>Phone: {receiptData.shop.phone}</div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: '12px', fontWeight: 800, color: '#2864d7' }}>RECEIPT / INVOICE</div>
                <div style={{ fontSize: '14px', fontWeight: 800 }}>#{receiptData.order_id}</div>
                <div style={{ fontSize: '11px', color: '#7a8b9f', marginTop: '2px' }}>{receiptData.order_date}</div>
                <div style={{ marginTop: '6px' }}>
                  <span className={`badge-payment ${receiptData.payment_status}`}>
                    PAYMENT: {receiptData.payment_status.toUpperCase()}
                  </span>
                </div>
              </div>
            </div>

            <div className="receipt-meta-grid">
              <div>
                <b>Billed To:</b>
                <div>{receiptData.customer.name}</div>
                <div>Phone: {receiptData.customer.phone || 'N/A'}</div>
                <div>Email: {receiptData.customer.email || 'N/A'}</div>
              </div>
              <div>
                <b>Order Details:</b>
                <div>Status: <span style={{ textTransform: 'capitalize' }}>{receiptData.status}</span></div>
                <div>Document: {receiptData.document.filename}</div>
                <div>
                  Pages: {receiptData.document.pages_selected} ({receiptData.document.actual_page_count || receiptData.document.page_count} actual pgs, {receiptData.document.billable_page_count || receiptData.breakdown?.billable_page_count || receiptData.document.page_count} billable pgs, {receiptData.document.sheets_used} sheets)
                </div>
              </div>
            </div>

            {(receiptData.requires_quote || receiptData.breakdown?.requires_quote) && (
              <div style={{ marginBottom: '16px', padding: '10px 14px', background: '#fff9ec', border: '1px solid #f9e2a6', borderRadius: '8px', fontSize: '12px', color: '#8f6204' }}>
                ⚠️ <b>Awaiting quotation:</b> {receiptData.quote_reason || receiptData.breakdown?.quote_reason || 'Final price requires confirmation by the print shop.'}
              </div>
            )}

            <table className="receipt-table">
              <thead>
                <tr>
                  <th>Specification</th>
                  <th>Detail</th>
                  <th>Rate</th>
                  <th style={{ textAlign: 'right' }}>Amount</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Printing ({receiptData.specifications.color_mode})</td>
                  <td>
                    {receiptData.specifications.copies} {receiptData.specifications.copies === 1 ? 'copy' : 'copies'} · {receiptData.document.billable_page_count || receiptData.breakdown?.billable_page_count || receiptData.document.page_count} billable pgs · {receiptData.specifications.paper_size} · {receiptData.specifications.sides} · {receiptData.specifications.orientation}
                  </td>
                  <td>{money(receiptData.breakdown?.effective_page_rate || receiptData.breakdown?.rate_per_page || receiptData.breakdown?.base_page_rate)}/pg</td>
                  <td style={{ textAlign: 'right' }}>
                    {receiptData.requires_quote || receiptData.breakdown?.requires_quote
                      ? 'Awaiting quote'
                      : money(receiptData.breakdown?.total_printing_cost)}
                  </td>
                </tr>
                {receiptData.breakdown?.total_finishing_cost > 0 && (
                  <tr>
                    <td>Finishing Service</td>
                    <td>Stapling ({receiptData.specifications.copies} sets)</td>
                    <td>{money(receiptData.breakdown?.finishing_unit_price)}/set</td>
                    <td style={{ textAlign: 'right' }}>{money(receiptData.breakdown?.total_finishing_cost)}</td>
                  </tr>
                )}
              </tbody>
            </table>

            <div className="receipt-total-box">
              <span>Total Amount (INR):</span>
              <span style={{ color: (receiptData.requires_quote || receiptData.breakdown?.requires_quote) ? '#b37400' : '#183b73', fontSize: (receiptData.requires_quote || receiptData.breakdown?.requires_quote) ? '16px' : '20px' }}>
                {receiptData.requires_quote || receiptData.breakdown?.requires_quote
                  ? 'Awaiting quotation'
                  : money(receiptData.final_amount_inr)}
              </span>
            </div>

            <div style={{ marginTop: '24px', fontSize: '11px', color: '#8898aa', textAlign: 'center', borderTop: '1px solid #edf1f7', paddingTop: '14px' }}>
              Thank you for printing with {receiptData.shop.name}! Powered by XeroxFlow SmartPrint.
            </div>
          </div>
        </div>

        <div className="modal-foot no-print">
          <button className="secondary" onClick={onClose}>Close</button>
          <button className="secondary" onClick={() => window.print()}>🖨 Print / Save Receipt</button>
          {user?.role === 'customer' ? (
            receiptData.payment_status === 'paid' ? (
              <button className="pill-btn active" disabled style={{ background: '#0d7d3c', color: '#fff', cursor: 'default', padding: '9px 16px', fontSize: '12px' }}>
                ✓ Paid
              </button>
            ) : (
              <button className="primary" onClick={onPay}>
                Pay
              </button>
            )
          ) : (
            receiptData.payment_status === 'pending' && onMarkPaid ? (
              <button
                className="primary"
                style={{ background: '#0d7d3c' }}
                onClick={() => onMarkPaid({ id: receiptData.order_id, final_price: receiptData.final_amount_inr })}
              >
                ✓ Payment Done
              </button>
            ) : (
              <button className="pill-btn active" disabled style={{ background: '#0d7d3c', color: '#fff', cursor: 'default', padding: '9px 16px', fontSize: '12px' }}>
                ✓ Payment Completed
              </button>
            )
          )}
        </div>
      </div>
    </div>
  );
}

function PayModal({ receiptData, onClose }) {
  return (
    <div className="modal-overlay no-print" onClick={onClose}>
      <div className="modal-box" onClick={e => e.stopPropagation()} style={{ maxWidth: '440px' }}>
        <div className="modal-head">
          <h3>Online Payment</h3>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body stack" style={{ textAlign: 'center', padding: '24px 20px' }}>
          <div style={{ fontSize: '44px', lineHeight: 1 }}>💳</div>
          <h4 style={{ margin: '6px 0 4px', fontSize: '18px', color: '#183b73' }}>Payment feature coming soon</h4>
          <p style={{ fontSize: '13px', color: '#65778f', lineHeight: 1.5, margin: 0 }}>
            Online payment will be available in a future update.
          </p>
          <div style={{ background: '#f5f7fb', border: '1px solid #e3e9f4', padding: '14px', borderRadius: '10px', fontSize: '12px', color: '#334862', textAlign: 'left', marginTop: '10px' }}>
            <div><b>Order ID:</b> #{receiptData?.order_id}</div>
            <div style={{ marginTop: '4px' }}><b>Shop:</b> {receiptData?.shop?.name}</div>
            <div style={{ marginTop: '4px' }}><b>Total Payable:</b> {money(receiptData?.final_amount_inr)}</div>
            <div style={{ marginTop: '8px', color: '#0d7d3c', fontWeight: 600 }}>
              ℹ Please pay in cash or counter UPI directly at the Xerox shop when collecting your printouts.
            </div>
          </div>
        </div>
        <div className="modal-foot">
          <button className="primary full" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}

function QrScannerModal({ isOpen, onClose, onSuccess, shops = [] }) {
  const [cameraError, setCameraError] = useState('');
  const [cameraLoading, setCameraLoading] = useState(true);
  const [fallbackShop, setFallbackShop] = useState('');
  const [invalidQrWarning, setInvalidQrWarning] = useState('');
  const scannerRef = useRef(null);
  const scannedRef = useRef(false);

  useEffect(() => {
    if (!isOpen) return;
    scannedRef.current = false;
    setCameraError('');
    setInvalidQrWarning('');
    setCameraLoading(true);

    let html5QrCode = null;

    const startTimer = setTimeout(() => {
      try {
        html5QrCode = new Html5Qrcode('qr-reader-container');
        scannerRef.current = html5QrCode;

        const config = {
          fps: 10,
          qrbox: { width: 240, height: 240 },
          aspectRatio: 1.0,
        };

        html5QrCode.start(
          { facingMode: 'environment' },
          config,
          (decodedText) => {
            if (scannedRef.current) return;
            const parsedShopId = parseShopIdFromQr(decodedText);
            if (parsedShopId) {
              scannedRef.current = true;
              try {
                html5QrCode.stop().then(() => {
                  try { html5QrCode.clear(); } catch {}
                  onSuccess(parsedShopId);
                }).catch(() => {
                  onSuccess(parsedShopId);
                });
              } catch {
                onSuccess(parsedShopId);
              }
            } else {
              setInvalidQrWarning(`Scanned code "${decodedText.slice(0, 35)}..." is not a recognized shop counter QR.`);
            }
          },
          () => {}
        ).then(() => {
          setCameraLoading(false);
        }).catch(err => {
          setCameraLoading(false);
          const errStr = String(err?.message || err);
          if (errStr.includes('NotAllowedError') || errStr.includes('Permission')) {
            setCameraError('Camera access was denied. Please allow camera permissions in your browser or select a shop manually below.');
          } else if (errStr.includes('NotFoundError') || errStr.includes('DevicesNotFoundError')) {
            setCameraError('No camera found on this device. You can select a shop manually below.');
          } else {
            setCameraError(`Camera initialization error: ${errStr}. You can select a shop manually below.`);
          }
        });
      } catch (e) {
        setCameraLoading(false);
        setCameraError(`Unable to start camera: ${e.message}`);
      }
    }, 150);

    return () => {
      clearTimeout(startTimer);
      if (scannerRef.current) {
        try {
          if (scannerRef.current.isScanning) {
            scannerRef.current.stop().then(() => {
              try { scannerRef.current.clear(); } catch {}
            }).catch(() => {});
          } else {
            try { scannerRef.current.clear(); } catch {}
          }
        } catch {}
      }
    };
  }, [isOpen]);

  if (!isOpen) return null;

  function handleManualConnect() {
    if (fallbackShop) {
      if (scannerRef.current && scannerRef.current.isScanning) {
        try {
          scannerRef.current.stop().then(() => {
            try { scannerRef.current.clear(); } catch {}
            onSuccess(fallbackShop);
          }).catch(() => onSuccess(fallbackShop));
        } catch {
          onSuccess(fallbackShop);
        }
      } else {
        onSuccess(fallbackShop);
      }
    }
  }

  return (
    <div className="modal-overlay no-print" onClick={onClose}>
      <div className="modal-box scanner-box" onClick={e => e.stopPropagation()}>
        <div className="modal-head">
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '20px' }}>📷</span>
            <h3 style={{ margin: 0, fontSize: '18px' }}>Scan Shop Counter QR</h3>
          </div>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>

        <div className="modal-body stack" style={{ padding: '18px 20px' }}>
          <p style={{ margin: '0 0 10px', fontSize: '13px', color: '#566a82' }}>
            Point your camera at the XeroxFlow QR code on the print shop counter.
          </p>

          {invalidQrWarning && (
            <div className="alert error" style={{ margin: '0 0 10px', fontSize: '12px' }}>
              ⚠️ {invalidQrWarning}
            </div>
          )}

          {cameraError ? (
            <div className="alert error" style={{ margin: '0 0 12px', fontSize: '13px', lineHeight: 1.4 }}>
              📷 <b>Camera Access Issue</b>
              <div style={{ marginTop: '4px' }}>{cameraError}</div>
            </div>
          ) : (
            <div className="scanner-viewport">
              {cameraLoading && (
                <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: '#fff', fontSize: '13px', gap: '10px', zIndex: 2 }}>
                  <div className="spinner"></div>
                  <span>Opening rear camera preview…</span>
                </div>
              )}
              <div id="qr-reader-container"></div>
              <div className="scanner-overlay-reticle">
                <div className="scan-line"></div>
              </div>
            </div>
          )}

          <div style={{ marginTop: '10px', padding: '12px 14px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '10px' }}>
            <div style={{ fontSize: '12px', fontWeight: 700, color: '#334155', marginBottom: '6px' }}>
              Or select shop manually:
            </div>
            <div style={{ display: 'flex', gap: '8px' }}>
              <select
                style={{ flex: 1, padding: '8px 10px', fontSize: '12px', borderRadius: '7px', border: '1px solid #cbd5e1', background: '#fff' }}
                value={fallbackShop}
                onChange={e => setFallbackShop(e.target.value)}
              >
                <option value="">Select a Xerox shop...</option>
                {shops.map(s => (
                  <option key={s.id} value={s.id}>
                    {s.name} ({s.address})
                  </option>
                ))}
              </select>
              <button
                className="primary small"
                disabled={!fallbackShop}
                onClick={handleManualConnect}
                style={{ whiteSpace: 'nowrap' }}
              >
                Connect →
              </button>
            </div>
          </div>
        </div>

        <div className="modal-foot">
          <button className="secondary full" onClick={onClose}>Cancel / Close</button>
        </div>
      </div>
    </div>
  );
}

function DirectUploadPage({ shop, shopId, loading, error, user, onAuthSuccess, onExit, onViewReceipt, onGoToOrders }) {
  const [selectedFile, setSelectedFile] = useState(null);
  const [fileError, setFileError] = useState('');
  const [inspectLoading, setInspectLoading] = useState(false);
  const [inspectedData, setInspectedData] = useState(null);

  const [options, setOptions] = useState({
    color_mode: 'bw',
    copies: 1,
    paper_size: 'A4',
    sides: 'single',
    notes: ''
  });

  const [estimate, setEstimate] = useState(null);
  const [estimating, setEstimating] = useState(false);
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState('');
  const [submittedOrder, setSubmittedOrder] = useState(null);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef(null);

  // Unauthenticated auth state
  const [authMode, setAuthMode] = useState('login');
  const [authForm, setAuthForm] = useState({ name: '', email: '', phone: '', password: '' });
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState('');

  // Handle unauthenticated visitor auth
  async function handleAuthSubmit(e) {
    e.preventDefault();
    setAuthError('');
    setAuthBusy(true);
    try {
      let path, body;
      if (authMode === 'register') {
        path = '/api/auth/register/customer';
        body = { name: authForm.name, email: authForm.email, phone: authForm.phone, password: authForm.password };
      } else {
        path = '/api/auth/login';
        body = { email: authForm.email, password: authForm.password };
      }
      const data = await request(path, { method: 'POST', body: JSON.stringify(body) });
      if (data.user.role !== 'customer') {
        throw new Error('Please log in with a customer account to upload documents.');
      }
      saveSession(data);
      onAuthSuccess(data.user, data.shop || null);
    } catch (err) {
      setAuthError(err.message || 'Authentication failed');
    } finally {
      setAuthBusy(false);
    }
  }

  // File validation and pre-flight inspection
  async function handleFileSelected(file) {
    setFileError('');
    setSubmitError('');
    setSubmittedOrder(null);

    if (!file) return;

    // Check empty file
    if (file.size === 0) {
      setFileError('The selected file is empty (0 bytes). Please choose a valid document.');
      setSelectedFile(null);
      setInspectedData(null);
      setEstimate(null);
      return;
    }

    // Check 15MB size limit
    const MAX_SIZE = 15 * 1024 * 1024;
    if (file.size > MAX_SIZE) {
      setFileError(`File size (${(file.size / (1024 * 1024)).toFixed(1)} MB) exceeds the 15MB limit.`);
      setSelectedFile(null);
      setInspectedData(null);
      setEstimate(null);
      return;
    }

    // Check extension
    const ext = '.' + (file.name.split('.').pop() || '').toLowerCase();
    const allowed = ['.pdf', '.png', '.jpg', '.jpeg', '.webp'];
    if (!allowed.includes(ext)) {
      setFileError(`Unsupported format "${ext}". Please upload a PDF or image file (PNG, JPG, WEBP).`);
      setSelectedFile(null);
      setInspectedData(null);
      setEstimate(null);
      return;
    }

    setSelectedFile(file);
    setInspectLoading(true);

    try {
      const fd = new FormData();
      fd.append('document', file);
      fd.append('shop_id', shopId);
      fd.append('color_mode', options.color_mode);
      fd.append('paper_size', options.paper_size);
      fd.append('sides', options.sides);
      fd.append('copies', options.copies);
      fd.append('pages', 'all');

      const data = await request('/api/pricing/inspect-document', { method: 'POST', body: fd });
      setInspectedData(data);
      if (data.breakdown) {
        setEstimate(data.breakdown);
      }
    } catch (err) {
      setFileError(err.message || 'Server rejected the file. Please ensure it is not corrupted or password-protected.');
      setSelectedFile(null);
      setInspectedData(null);
      setEstimate(null);
    } finally {
      setInspectLoading(false);
    }
  }

  // Recalculate price estimate when options change and document is selected
  useEffect(() => {
    if (!selectedFile || !inspectedData || !shop) return;

    let isMounted = true;
    setEstimating(true);

    const timer = setTimeout(async () => {
      try {
        const est = await request('/api/pricing/estimate', {
          method: 'POST',
          body: JSON.stringify({
            shop_id: Number(shopId),
            copies: Number(options.copies || 1),
            pages: `1-${inspectedData.actual_page_count || 1}`,
            color_mode: options.color_mode,
            paper_size: options.paper_size,
            sides: options.sides,
            orientation: 'portrait',
            finishing: 'none'
          })
        });
        if (isMounted) setEstimate(est);
      } catch {
        // keep prior estimate
      } finally {
        if (isMounted) setEstimating(false);
      }
    }, 200);

    return () => {
      isMounted = false;
      clearTimeout(timer);
    };
  }, [options.color_mode, options.copies, options.paper_size, options.sides, inspectedData?.actual_page_count]);

  // Submit print order
  async function handleConfirmSubmit() {
    setShowConfirmModal(false);
    setSubmitting(true);
    setSubmitError('');

    try {
      const fd = new FormData();
      fd.append('shop_id', shopId);
      fd.append('document', selectedFile);
      fd.append('copies', options.copies);
      fd.append('pages', 'all');
      fd.append('color_mode', options.color_mode);
      fd.append('paper_size', options.paper_size);
      fd.append('sides', options.sides);
      fd.append('orientation', 'portrait');
      fd.append('finishing', 'none');
      if (options.notes) fd.append('notes', options.notes);

      const orderOut = await request('/api/orders', { method: 'POST', body: fd });
      setSubmittedOrder(orderOut);
    } catch (err) {
      setSubmitError(err.message || 'Order submission failed');
    } finally {
      setSubmitting(false);
    }
  }

  // Render Loading
  if (loading) {
    return (
      <div className="panel" style={{ textAlign: 'center', padding: '48px 24px' }}>
        <div style={{ fontSize: '36px', marginBottom: '14px' }}>🔄</div>
        <h3 style={{ margin: '0 0 8px' }}>Connecting to Xerox Shop...</h3>
        <p className="muted" style={{ margin: 0 }}>Validating shop counter and retrieving active rates...</p>
      </div>
    );
  }

  // Render Error
  if (error || !shop) {
    return (
      <div className="panel" style={{ textAlign: 'center', padding: '48px 24px' }}>
        <div style={{ fontSize: '36px', marginBottom: '14px', color: '#b3343c' }}>⚠️</div>
        <h3 style={{ margin: '0 0 8px', color: '#b3343c' }}>Shop Not Found or Inactive</h3>
        <p style={{ color: '#56677f', margin: '0 0 20px', fontSize: '14px' }}>
          {error || `Shop #${shopId} does not exist or is currently not accepting print jobs.`}
        </p>
        <button className="primary" onClick={onExit}>
          Return to Dashboard
        </button>
      </div>
    );
  }

  // Render Unauthenticated Flow
  if (!user) {
    return (
      <div className="stack" style={{ maxWidth: '520px', margin: '0 auto' }}>
        <div className="direct-shop-header">
          <div className="direct-shop-title-row">
            <div>
              <div className="eyebrow" style={{ color: '#2864d7' }}>COUNTER PRINTING</div>
              <h1 className="direct-shop-heading">Printing at {shop.name}</h1>
              <div className="direct-shop-meta">
                <span>📍 {shop.address}</span>
                <span>📞 {shop.phone}</span>
                <span className="online-dot">● Active</span>
              </div>
            </div>
            <div className="direct-rates-badge">
              <span>B/W: {money(shop.bw_price)}/pg</span>
              <span>·</span>
              <span>Colour: {money(shop.color_price)}/pg</span>
            </div>
          </div>
        </div>

        <section className="auth-card" style={{ width: '100%', margin: '0' }}>
          <div className="eyebrow">CUSTOMER LOGIN REQUIRED</div>
          <h2 style={{ fontFamily: 'Manrope, sans-serif', fontSize: '20px', margin: '8px 0 6px' }}>
            {authMode === 'login' ? 'Log in to upload your document' : 'Create customer account to print'}
          </h2>
          <p className="muted" style={{ margin: '0 0 16px', fontSize: '13px' }}>
            Log in or sign up to upload private documents directly to {shop.name}.
          </p>

          <form onSubmit={handleAuthSubmit} className="stack">
            {authMode === 'register' && (
              <>
                <label>Your full name<input required minLength="2" value={authForm.name} onChange={e => setAuthForm(f => ({ ...f, name: e.target.value }))} placeholder="Full name" /></label>
                <label>Phone number<input required value={authForm.phone} onChange={e => setAuthForm(f => ({ ...f, phone: e.target.value }))} placeholder="+91..." /></label>
              </>
            )}
            <label>Email address<input type="email" required value={authForm.email} onChange={e => setAuthForm(f => ({ ...f, email: e.target.value }))} placeholder="you@example.com" /></label>
            <label>Password<input type="password" required minLength="8" value={authForm.password} onChange={e => setAuthForm(f => ({ ...f, password: e.target.value }))} placeholder="At least 8 characters" /></label>
            {authError && <div className="alert error">{authError}</div>}
            <button className="primary" disabled={authBusy}>
              {authBusy ? 'Please wait…' : authMode === 'login' ? 'Log in & Open File Picker' : 'Create Account & Continue'}
            </button>
          </form>

          <p className="auth-foot" style={{ marginTop: '16px' }}>
            {authMode === 'login' ? 'First time here?' : 'Already have an account?'}
            {' '}
            <button className="link" onClick={() => { setAuthMode(m => m === 'login' ? 'register' : 'login'); setAuthError(''); }}>
              {authMode === 'login' ? 'Create free account' : 'Log in'}
            </button>
          </p>
          <div style={{ textAlign: 'center', marginTop: '12px' }}>
            <button className="link text-button" style={{ fontSize: '12px', color: '#7a8b9f' }} onClick={onExit}>
              ← Leave & return to home
            </button>
          </div>
        </section>
      </div>
    );
  }

  // Render Shopkeeper Notice if user is shopkeeper
  if (user.role === 'shopkeeper') {
    return (
      <div className="panel" style={{ textAlign: 'center', padding: '40px 24px' }}>
        <div style={{ fontSize: '32px', marginBottom: '12px' }}>ℹ️</div>
        <h3>Shopkeeper Account Active</h3>
        <p className="muted" style={{ margin: '8px 0 20px', fontSize: '14px' }}>
          You are currently logged in as a shopkeeper ({user.name}). To place an order at {shop.name}, please log in with a customer account.
        </p>
        <button className="primary" onClick={onExit}>
          Go to Shopkeeper Dashboard
        </button>
      </div>
    );
  }

  // Render Submitted Order Success View
  if (submittedOrder) {
    return (
      <div className="stack" style={{ maxWidth: '640px', margin: '0 auto' }}>
        <div className="panel" style={{ textAlign: 'center', padding: '36px 24px' }}>
          <div style={{
            width: '64px',
            height: '64px',
            borderRadius: '50%',
            background: '#e6f7ed',
            color: '#18834f',
            display: 'grid',
            placeItems: 'center',
            fontSize: '32px',
            margin: '0 auto 16px',
            fontWeight: 800
          }}>
            ✓
          </div>
          <h2 style={{ fontFamily: 'Manrope, sans-serif', fontSize: '24px', margin: '0 0 6px', color: '#182d4d' }}>
            Order Placed Successfully!
          </h2>
          <div style={{ fontSize: '16px', fontWeight: 700, color: '#2864d7', marginBottom: '10px' }}>
            Order #{submittedOrder.id}
          </div>
          <p style={{ color: '#56677f', fontSize: '14px', margin: '0 auto 20px', maxWidth: '440px' }}>
            Your print job for <b>{submittedOrder.original_filename}</b> has been received by <b>{shop.name}</b>.
          </p>

          <div style={{ background: '#f5f7fb', border: '1px solid #e3e9f4', padding: '16px', borderRadius: '12px', margin: '0 0 24px', textAlign: 'left', fontSize: '13px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
              <span style={{ color: '#68778d' }}>Print Shop:</span>
              <b>{shop.name}</b>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
              <span style={{ color: '#68778d' }}>Options:</span>
              <span>{submittedOrder.color_mode === 'bw' ? 'B/W' : 'Colour'} · {submittedOrder.copies} {submittedOrder.copies === 1 ? 'copy' : 'copies'} · {submittedOrder.paper_size} · {submittedOrder.sides}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', borderTop: '1px solid #e2e8f0', paddingTop: '8px', marginTop: '8px', fontWeight: 800 }}>
              <span>Total Payable at Counter:</span>
              <span style={{ color: '#183b73', fontSize: '16px' }}>{money(submittedOrder.final_price || submittedOrder.estimated_price)}</span>
            </div>
            <div style={{ marginTop: '10px', fontSize: '11px', color: '#0d7d3c', fontWeight: 600 }}>
              ℹ Collect your documents at the shop counter and pay via Cash or UPI upon pickup.
            </div>
          </div>

          <div style={{ display: 'flex', gap: '12px', justifyContent: 'center', flexWrap: 'wrap' }}>
            <button className="primary" onClick={() => onViewReceipt(submittedOrder)}>
              🖨 View Official Receipt
            </button>
            <button className="secondary" onClick={onGoToOrders}>
              ▤ Track in My Orders
            </button>
            <button className="secondary" onClick={() => {
              setSubmittedOrder(null);
              setSelectedFile(null);
              setInspectedData(null);
              setEstimate(null);
            }}>
              + Print Another Document
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Render Direct Upload Main Screen
  return (
    <div className="stack" style={{ maxWidth: '680px', margin: '0 auto' }}>
      {/* Shop Header */}
      <div className="direct-shop-header">
        <div className="direct-shop-title-row">
          <div>
            <div className="eyebrow" style={{ color: '#2864d7' }}>DIRECT PRINTING COUNTER</div>
            <h1 className="direct-shop-heading">Printing at {shop.name}</h1>
            <div className="direct-shop-meta">
              <span>📍 {shop.address}</span>
              <span>📞 {shop.phone}</span>
              <span className="online-dot">● Active</span>
            </div>
          </div>
          <div className="direct-rates-badge">
            <span>B/W: {money(shop.bw_price)}/pg</span>
            <span>·</span>
            <span>Colour: {money(shop.color_price)}/pg</span>
          </div>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '1px solid #f0f4fa', paddingTop: '10px', marginTop: '6px', fontSize: '12px' }}>
          <span style={{ color: '#56677f' }}>
            👤 Ordering as <b>{user.name}</b> ({user.phone || user.email})
          </span>
          <button className="link text-button" style={{ fontSize: '12px' }} onClick={onExit}>
            ← Change Shop / Dashboard
          </button>
        </div>
      </div>

      {submitError && (
        <div className="alert error">
          ⚠️ {submitError}
        </div>
      )}

      {/* STEP 1: Select Document */}
      {!selectedFile ? (
        <div
          className={`direct-browse-card ${dragActive ? 'drag-active' : ''}`}
          onDragOver={e => { e.preventDefault(); setDragActive(true); }}
          onDragLeave={() => setDragActive(false)}
          onDrop={e => {
            e.preventDefault();
            setDragActive(false);
            const f = e.dataTransfer.files?.[0];
            if (f) handleFileSelected(f);
          }}
        >
          <div style={{ fontSize: '48px', lineHeight: 1 }}>📄</div>
          <div>
            <h3 style={{ margin: '0 0 6px', fontSize: '18px', color: '#182d4d' }}>
              Select the document you want to print
            </h3>
            <p className="muted" style={{ margin: 0, fontSize: '13px' }}>
              Tap below to choose a file from your device. PDF, PNG, JPG, or WEBP supported (Max 15MB).
            </p>
          </div>

          <button
            type="button"
            className="browse-primary-btn"
            onClick={() => fileInputRef.current?.click()}
          >
            <span style={{ fontSize: '20px' }}>📁</span>
            <span>Browse Documents / Upload Files</span>
          </button>

          <input
            type="file"
            ref={fileInputRef}
            style={{ display: 'none' }}
            accept=".pdf,.png,.jpg,.jpeg,.webp"
            onChange={e => {
              const f = e.target.files?.[0];
              if (f) handleFileSelected(f);
              e.target.value = '';
            }}
          />

          {fileError && (
            <div className="alert error" style={{ width: '100%', textAlign: 'left', marginTop: '10px' }}>
              ⚠️ {fileError}
            </div>
          )}

          <div style={{ display: 'flex', gap: '16px', justifyContent: 'center', flexWrap: 'wrap', fontSize: '11px', color: '#7a8b9f', marginTop: '8px' }}>
            <span>✓ Server Page Count</span>
            <span>✓ Instant Live Pricing</span>
            <span>✓ Pay at Counter</span>
          </div>
        </div>
      ) : (
        <>
          {/* Selected File Box */}
          <div className="file-selected-box">
            <div className="file-selected-info">
              <div className="file-selected-icon">
                {selectedFile.name.toLowerCase().endsWith('.pdf') ? 'PDF' : 'IMG'}
              </div>
              <div className="file-selected-names">
                <div className="file-selected-filename" title={selectedFile.name}>
                  {selectedFile.name}
                </div>
                <div className="file-selected-details">
                  <span>{(selectedFile.size / 1024).toFixed(1)} KB</span>
                  {inspectLoading ? (
                    <span style={{ color: '#2864d7' }}>Analyzing pages...</span>
                  ) : inspectedData ? (
                    <span className="badge-pages">
                      📄 {inspectedData.actual_page_count} {inspectedData.actual_page_count === 1 ? 'Page' : 'Pages'} Detected ({inspectedData.sheets_used} {inspectedData.sheets_used === 1 ? 'sheet' : 'sheets'})
                    </span>
                  ) : null}
                </div>
              </div>
            </div>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              <button
                type="button"
                className="text-button"
                style={{ fontSize: '12px' }}
                onClick={() => fileInputRef.current?.click()}
              >
                Change
              </button>
              <button
                type="button"
                className="text-button"
                style={{ fontSize: '12px', color: '#b3343c' }}
                onClick={() => {
                  setSelectedFile(null);
                  setInspectedData(null);
                  setEstimate(null);
                  setFileError('');
                }}
              >
                ✕ Remove
              </button>
              <input
                type="file"
                ref={fileInputRef}
                style={{ display: 'none' }}
                accept=".pdf,.png,.jpg,.jpeg,.webp"
                onChange={e => {
                  const f = e.target.files?.[0];
                  if (f) handleFileSelected(f);
                  e.target.value = '';
                }}
              />
            </div>
          </div>

          {fileError && (
            <div className="alert error">
              ⚠️ {fileError}
            </div>
          )}

          {/* STEP 2: Minimal Print Options (Revealed ONLY AFTER document selection) */}
          <div className="minimal-options-card stack">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3 style={{ margin: 0, fontSize: '16px', color: '#182d4d', fontFamily: 'Manrope, sans-serif' }}>
                Print Settings
              </h3>
              <span style={{ fontSize: '11px', color: '#7a8b9f' }}>Step 2 of 2</span>
            </div>

            {/* Color Mode */}
            <div>
              <label style={{ fontSize: '12px', fontWeight: 700, color: '#334862', display: 'block', marginBottom: '6px' }}>
                Printing Color
              </label>
              <div className="segment-group">
                <button
                  type="button"
                  className={`segment-btn ${options.color_mode === 'bw' ? 'active' : ''}`}
                  onClick={() => setOptions(o => ({ ...o, color_mode: 'bw' }))}
                >
                  ⚪ Black & White ({money(shop.bw_price)}/pg)
                </button>
                <button
                  type="button"
                  className={`segment-btn ${options.color_mode === 'color' ? 'active' : ''}`}
                  onClick={() => setOptions(o => ({ ...o, color_mode: 'color' }))}
                >
                  🎨 Colour ({money(shop.color_price)}/pg)
                </button>
              </div>
            </div>

            {/* Copies and Paper Size */}
            <div className="form-grid">
              <div>
                <label style={{ fontSize: '12px', fontWeight: 700, color: '#334862', display: 'block', marginBottom: '6px' }}>
                  Number of Copies
                </label>
                <div className="stepper-control">
                  <button
                    type="button"
                    className="stepper-btn"
                    onClick={() => setOptions(o => ({ ...o, copies: Math.max(1, (o.copies || 1) - 1) }))}
                    disabled={options.copies <= 1}
                  >
                    −
                  </button>
                  <input
                    type="number"
                    min="1"
                    max="100"
                    className="stepper-value"
                    value={options.copies}
                    onChange={e => {
                      const v = parseInt(e.target.value) || 1;
                      setOptions(o => ({ ...o, copies: Math.max(1, Math.min(100, v)) }));
                    }}
                  />
                  <button
                    type="button"
                    className="stepper-btn"
                    onClick={() => setOptions(o => ({ ...o, copies: Math.min(100, (o.copies || 1) + 1) }))}
                    disabled={options.copies >= 100}
                  >
                    +
                  </button>
                </div>
              </div>

              <div>
                <label style={{ fontSize: '12px', fontWeight: 700, color: '#334862', display: 'block', marginBottom: '6px' }}>
                  Paper Size
                </label>
                <div className="segment-group">
                  {['A4', 'A3', 'A5'].map(sz => (
                    <button
                      key={sz}
                      type="button"
                      className={`segment-btn ${options.paper_size === sz ? 'active' : ''}`}
                      onClick={() => setOptions(o => ({ ...o, paper_size: sz }))}
                    >
                      {sz}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Sides */}
            <div>
              <label style={{ fontSize: '12px', fontWeight: 700, color: '#334862', display: 'block', marginBottom: '6px' }}>
                Printing Sides
              </label>
              <div className="segment-group">
                <button
                  type="button"
                  className={`segment-btn ${options.sides === 'single' ? 'active' : ''}`}
                  onClick={() => setOptions(o => ({ ...o, sides: 'single' }))}
                >
                  Single-sided
                </button>
                <button
                  type="button"
                  className={`segment-btn ${options.sides === 'double' ? 'active' : ''}`}
                  onClick={() => setOptions(o => ({ ...o, sides: 'double' }))}
                >
                  Double-sided {shop.double_sided_discount > 0 ? `(Save ${money(shop.double_sided_discount)}/pg)` : ''}
                </button>
              </div>
            </div>

            {/* Optional Customer Instructions */}
            <div>
              <label style={{ fontSize: '12px', fontWeight: 700, color: '#334862', display: 'block', marginBottom: '6px' }}>
                Instructions / Notes for Shopkeeper (Optional)
              </label>
              <input
                type="text"
                placeholder="e.g. Staple top-left, print on thick paper if available"
                value={options.notes}
                onChange={e => setOptions(o => ({ ...o, notes: e.target.value }))}
                style={{ padding: '10px 12px', fontSize: '13px', borderRadius: '8px', border: '1px solid #dce3ed', width: '100%' }}
              />
            </div>
          </div>

          {/* Live Price Breakdown Card */}
          <div className="price-breakdown-card">
            <div className="breakdown-title">Itemized Counter Price Estimate</div>
            <div className="breakdown-row">
              <span>Rate per page ({options.color_mode.toUpperCase()}, {options.paper_size}):</span>
              <b>{money(estimate?.effective_page_rate || estimate?.rate_per_page || (options.color_mode === 'bw' ? shop.bw_price : shop.color_price))}/page</b>
            </div>
            <div className="breakdown-row">
              <span>
                Printing ({options.copies} {options.copies === 1 ? 'copy' : 'copies'} × {inspectedData?.billable_page_count || inspectedData?.actual_page_count || 1} {inspectedData?.actual_page_count === 1 ? 'page' : 'pages'}):
              </span>
              <b>{estimate?.requires_quote ? 'Awaiting quote' : money(estimate?.total_printing_cost || 0)}</b>
            </div>
            <div className="breakdown-row total">
              <span>Total Amount:</span>
              <b style={{ color: estimate?.requires_quote ? '#b37400' : '#2864d7' }}>
                {estimating ? 'Calculating…' : estimate?.requires_quote ? 'Awaiting shopkeeper quotation' : money(estimate?.total_price || 0)}
              </b>
            </div>
            <div className="breakdown-note">
              ✓ Server-verified page count. You will review and confirm this price before submission.
            </div>
          </div>

          {/* Explicit Order Confirmation Trigger */}
          <button
            type="button"
            className="primary full"
            style={{ padding: '15px', fontSize: '15px', fontWeight: 800 }}
            disabled={inspectLoading || submitting || !inspectedData}
            onClick={() => setShowConfirmModal(true)}
          >
            {submitting ? 'Placing Order…' : `Review & Confirm Order • ${estimate?.requires_quote ? 'Quote Required' : money(estimate?.total_price || 0)}`}
          </button>
        </>
      )}

      {/* Explicit Order Review & Confirmation Modal */}
      {showConfirmModal && (
        <div className="modal-overlay" onClick={() => setShowConfirmModal(false)}>
          <div className="modal-box" onClick={e => e.stopPropagation()} style={{ maxWidth: '480px' }}>
            <div className="modal-head">
              <h3 style={{ margin: 0, fontSize: '18px' }}>Confirm Print Order</h3>
              <button className="modal-close" onClick={() => setShowConfirmModal(false)}>×</button>
            </div>
            <div className="modal-body stack" style={{ padding: '20px' }}>
              <p style={{ margin: '0 0 12px', fontSize: '13px', color: '#56677f' }}>
                Please review your print specifications before submitting to <b>{shop.name}</b>:
              </p>

              <div style={{ background: '#f5f7fb', border: '1px solid #e3e9f4', padding: '14px', borderRadius: '10px', fontSize: '12px' }}>
                <div style={{ marginBottom: '6px' }}><b>Shop:</b> {shop.name} ({shop.address})</div>
                <div style={{ marginBottom: '6px' }}><b>Document:</b> {selectedFile?.name} ({inspectedData?.actual_page_count || 1} pages)</div>
                <div style={{ marginBottom: '6px' }}>
                  <b>Print Mode:</b> {options.color_mode === 'bw' ? 'Black & White' : 'Colour'} · {options.copies} {options.copies === 1 ? 'copy' : 'copies'} · {options.paper_size} · {options.sides}
                </div>
                {options.notes && <div style={{ marginBottom: '6px' }}><b>Instructions:</b> {options.notes}</div>}
                <div style={{ borderTop: '1px solid #e2e8f0', paddingTop: '8px', marginTop: '8px', display: 'flex', justifyContent: 'space-between', fontSize: '14px', fontWeight: 800 }}>
                  <span>Total Payable:</span>
                  <span style={{ color: '#183b73' }}>
                    {estimate?.requires_quote ? 'Awaiting shopkeeper quotation' : money(estimate?.total_price)}
                  </span>
                </div>
              </div>

              <div style={{ fontSize: '11px', color: '#0d7d3c', background: '#f0fbf4', padding: '10px 12px', borderRadius: '8px', border: '1px solid #bcebc8' }}>
                ℹ Payment is collected at the shop counter upon pickup (Cash or UPI). No online payment is charged now.
              </div>
            </div>
            <div className="modal-foot">
              <button className="secondary" onClick={() => setShowConfirmModal(false)}>
                Back to Edit
              </button>
              <button className="primary" onClick={handleConfirmSubmit} disabled={submitting}>
                {submitting ? 'Submitting…' : `Yes, Place Order (${estimate?.requires_quote ? 'Awaiting Quote' : money(estimate?.total_price)})`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

