"use client";

import { useEffect, useState } from "react";

type ServiceState = "checking" | "ready" | "unavailable" | "offline";
type AccountState = "checking" | "signed-in" | "signed-out" | "unavailable";
type MerchantAccount = {
  user: { full_name: string; email: string };
  merchant: { business_name: string };
};
type RecentPayment = {
  id: string;
  reference: string;
  description: string;
  amount: string;
  currency: string;
  status: string;
  created_at: string;
  checkout_url: string;
};

const navigation = [
  { label: "Overview", href: "#overview" },
  { label: "Activity", href: "#activity" },
  { label: "Risk signals", href: "#risk" },
  { label: "Services", href: "#services" },
];

const metrics = [
  { label: "Transactions", detail: "Payment tracking not connected" },
  { label: "Payment volume", detail: "No settlement data yet" },
  { label: "Held in escrow", detail: "Contract not deployed" },
  { label: "Risk assessments", detail: "AI service not configured" },
];

function useBackendHealth(): ServiceState {
  const [state, setState] = useState<ServiceState>("checking");

  useEffect(() => {
    const apiUrl = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
    const controller = new AbortController();

    async function checkHealth() {
      try {
        const response = await fetch(`${apiUrl}/health/ready`, {
          cache: "no-store",
          signal: controller.signal,
        });
        setState(response.ok ? "ready" : "unavailable");
      } catch {
        if (!controller.signal.aborted) setState("offline");
      }
    }

    void checkHealth();
    const intervalId = window.setInterval(checkHealth, 15000);

    return () => {
      controller.abort();
      window.clearInterval(intervalId);
    };
  }, []);

  return state;
}

function useMerchantAccount() {
  const [account, setAccount] = useState<MerchantAccount | null>(null);
  const [state, setState] = useState<AccountState>("checking");

  useEffect(() => {
    const apiUrl = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
    const controller = new AbortController();

    async function loadAccount() {
      try {
        let response = await fetch(`${apiUrl}/api/v1/auth/me`, {
          credentials: "include",
          cache: "no-store",
          signal: controller.signal,
        });
        if (response.status === 401) {
          const refreshed = await fetch(`${apiUrl}/api/v1/auth/refresh`, {
            method: "POST",
            credentials: "include",
            signal: controller.signal,
          });
          if (refreshed.ok) {
            response = await fetch(`${apiUrl}/api/v1/auth/me`, {
              credentials: "include",
              cache: "no-store",
              signal: controller.signal,
            });
          }
        }
        if (controller.signal.aborted) return;
        if (response.ok) {
          setAccount(await response.json() as MerchantAccount);
          setState("signed-in");
        } else if (response.status === 401) {
          setAccount(null);
          setState("signed-out");
        } else {
          setState("unavailable");
        }
      } catch {
        if (!controller.signal.aborted) setState("unavailable");
      }
    }

    void loadAccount();
    return () => controller.abort();
  }, []);

  return { account, state, setAccount, setState };
}

function useRecentPayments(enabled: boolean) {
  const [payments, setPayments] = useState<RecentPayment[]>([]);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!enabled) {
      setPayments([]);
      setFailed(false);
      return;
    }
    const apiUrl = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
    const controller = new AbortController();

    async function loadPayments() {
      try {
        const response = await fetch(`${apiUrl}/api/v1/payments?limit=5`, {
          credentials: "include",
          cache: "no-store",
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        if (!response.ok) {
          setFailed(true);
          return;
        }
        setPayments(await response.json() as RecentPayment[]);
        setFailed(false);
      } catch {
        if (!controller.signal.aborted) setFailed(true);
      }
    }

    void loadPayments();
    const intervalId = window.setInterval(loadPayments, 15000);
    return () => {
      controller.abort();
      window.clearInterval(intervalId);
    };
  }, [enabled]);

  return { payments, failed };
}

function HealthLabel({ state }: { state: ServiceState }) {
  const labels: Record<ServiceState, string> = {
    checking: "Checking services",
    ready: "API and data services ready",
    unavailable: "API dependencies unavailable",
    offline: "API unreachable",
  };

  return (
    <span className={`health-label health-${state}`} role="status" aria-live="polite">
      <span className="status-dot" aria-hidden="true" />
      {labels[state]}
    </span>
  );
}

export default function Home() {
  const backendHealth = useBackendHealth();
  const { account, state: accountState, setAccount, setState } = useMerchantAccount();
  const { payments, failed: paymentsFailed } = useRecentPayments(Boolean(account));

  async function signOut() {
    const apiUrl = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
    try {
      await fetch(`${apiUrl}/api/v1/auth/logout`, { method: "POST", credentials: "include" });
    } finally {
      setAccount(null);
      setState("signed-out");
    }
  }

  return (
    <div className="app-shell" id="overview">
      <aside className="sidebar">
        <a className="brand" href="#overview" aria-label="SentinelPay overview">
          <span className="brand-mark" aria-hidden="true">S</span>
          <span className="brand-name">sentinel<span>pay</span></span>
        </a>

        <div className="workspace-label">MERCHANT WORKSPACE</div>
        <nav className="main-nav" aria-label="Main navigation">
          {navigation.map((item, index) => (
            <a
              className={`nav-link${index === 0 ? " nav-link-active" : ""}`}
              href={item.href}
              key={item.href}
              aria-current={index === 0 ? "page" : undefined}
            >
              <span className="nav-marker" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
              {item.label}
            </a>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <span className="eyebrow">ENVIRONMENT</span>
          <div className="environment-value"><span className="status-dot status-dot-amber" />Testnet setup</div>
          <p>Sepolia target. Wallet and contract are not connected.</p>
          <div className="sidebar-rule" />
          <span className="sidebar-footnote">SENTINELPAY <span>·</span> PHASE 1</span>
        </div>
      </aside>

      <div className="main-column">
        <header className="topbar">
          <span className="breadcrumb">Workspace <span>/</span> Overview</span>
          <div className="topbar-actions">
            <HealthLabel state={backendHealth} />
            {account ? (
              <div className="account-control">
                <span className="account-name" title={account.user.email}>{account.merchant.business_name}</span>
                <button className="signout-button" onClick={signOut} type="button">Sign out</button>
              </div>
            ) : accountState === "signed-out" ? (
              <div className="account-control"><a href="/login">Sign in</a><a href="/register">Register</a></div>
            ) : (
              <span className="account-state" role="status">{accountState === "checking" ? "Checking account" : "Account unavailable"}</span>
            )}
          </div>
        </header>

        <main className="dashboard-content">
          <section className="page-heading" aria-labelledby="page-title">
            <div>
              <p className="eyebrow">PAYMENT SECURITY</p>
              <h1 id="page-title">Your security overview</h1>
              <p className="page-intro">A clear view of payment activity, risk, and settlement health.</p>
            </div>
            <div className="heading-actions">
              <span className="network-tag"><span className="status-dot status-dot-amber" />SEPOLIA TARGET</span>
              {account ? <a className="create-payment-link" href="/dashboard/payments/new">Create payment</a> : <a className="create-payment-link create-payment-muted" href="/login">Sign in to create a payment</a>}
            </div>
          </section>

          <section className="metrics-grid" aria-label="Payment metrics">
            {metrics.map((metric, index) => (
              <article className="metric-panel" key={metric.label}>
                <div className="metric-topline">
                  <span className="metric-index">0{index + 1}</span>
                  <span className="metric-period">LIVE DATA</span>
                </div>
                <h2>{metric.label}</h2>
                <p className="metric-value" aria-label={`${metric.label}: not available`}>—</p>
                <p className="metric-detail">{metric.detail}</p>
              </article>
            ))}
          </section>

          <div className="dashboard-grid">
            <section className="panel activity-panel" id="activity" aria-labelledby="activity-title">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">PAYMENT FLOW</p>
                  <h2 id="activity-title">Recent activity</h2>
                </div>
                <span className="panel-note">TRANSACTIONS</span>
              </div>
              <div className="empty-state">
                <div className="empty-rule" aria-hidden="true"><span /></div>
                <h3>No payment activity yet</h3>
                {paymentsFailed ? (
                  <p>Payment requests could not be loaded from the API.</p>
                ) : account && payments.length > 0 ? (
                  <div className="payment-activity-list">
                    {payments.map((payment) => (
                      <a className="payment-activity-row" href={payment.checkout_url} key={payment.id}>
                        <span className="payment-activity-main">
                          <strong>{payment.description}</strong>
                          <small>{new Date(payment.created_at).toLocaleString()}</small>
                        </span>
                        <span className="payment-activity-meta">
                          <strong>{payment.amount} {payment.currency}</strong>
                          <small>{payment.status.replaceAll("_", " ")}</small>
                        </span>
                      </a>
                    ))}
                    <a className="text-action" href="/dashboard/payments/new">Create another payment request</a>
                  </div>
                ) : (
                  <>
                    <p>{account ? "No payment requests yet. On-chain history appears when escrow monitoring is connected." : "Payment request history is available after merchant sign-in."}</p>
                    {account && <a className="text-action" href="/dashboard/payments/new">Create a payment request</a>}
                  </>
                )}
              </div>
            </section>

            <section className="panel risk-panel" id="risk" aria-labelledby="risk-title">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">AI MONITORING</p>
                  <h2 id="risk-title">Risk signals</h2>
                </div>
                <span className="signal-mark" aria-hidden="true">RISK</span>
              </div>
              <div className="risk-empty">
                <div className="risk-scale" aria-hidden="true"><span /><span /><span /></div>
                <h3>Assessment service not connected</h3>
                <p>No transaction scores or explanations are being generated yet.</p>
              </div>
              <div className="risk-footer"><span>MODEL STATUS</span><strong>NOT CONFIGURED</strong></div>
            </section>
          </div>

          <section className="panel services-panel" id="services" aria-labelledby="services-title">
            <div className="panel-heading services-heading">
              <div>
                <p className="eyebrow">FOUNDATION STATUS</p>
                <h2 id="services-title">Connected services</h2>
              </div>
              <p className="panel-description">Live readiness checks; unavailable integrations are not simulated.</p>
            </div>
            <div className="service-list">
              <div className="service-row">
                <span className="service-name">API, PostgreSQL, Redis</span>
                <HealthLabel state={backendHealth} />
              </div>
              <div className="service-row">
                <span className="service-name">AI risk engine</span>
                <span className="service-state"><span className="status-dot status-dot-muted" />Not configured</span>
              </div>
              <div className="service-row">
                <span className="service-name">Sepolia escrow</span>
                <span className="service-state"><span className="status-dot status-dot-muted" />Not deployed</span>
              </div>
            </div>
          </section>

          <footer className="page-footer">
            <span>SentinelPay <span className="footer-separator">/</span> Trust every transaction.</span>
            <span>Testnet only <span className="footer-separator">·</span> No production payments</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
