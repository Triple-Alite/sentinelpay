import type { Metadata } from "next";
import { PaymentCreateForm } from "@/components/payment-create-form";

export const metadata: Metadata = {
  title: "Create payment request | SentinelPay",
};

export default function NewPaymentPage() {
  return (
    <main className="auth-shell payment-page-shell">
      <aside className="auth-aside">
        <a className="brand" href="/" aria-label="SentinelPay dashboard">
          <span className="brand-mark" aria-hidden="true">S</span>
          <span className="brand-name">sentinel<span>pay</span></span>
        </a>
        <div className="auth-aside-copy">
          <p className="eyebrow">MERCHANT WORKSPACE</p>
          <h1>Start with a clear request.</h1>
          <p>Every payment begins with a merchant-owned request and a public checkout reference.</p>
        </div>
        <span className="auth-aside-foot">SENTINELPAY <span>·</span> SEPOLIA TESTNET</span>
      </aside>
      <section className="auth-main payment-main" aria-labelledby="payment-title">
        <div className="payment-page-content">
          <a className="back-link" href="/">← Back to overview</a>
          <p className="eyebrow">PAYMENT REQUEST</p>
          <h2 id="payment-title">Create a payment</h2>
          <p className="auth-intro">Create a checkout link for one order. Payment settlement is not enabled yet.</p>
          <PaymentCreateForm />
        </div>
      </section>
    </main>
  );
}