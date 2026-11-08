import type { Metadata } from "next";
import { AuthForm } from "@/components/auth-form";

export const metadata: Metadata = {
  title: "Sign in | SentinelPay",
};

export default function LoginPage() {
  return (
    <main className="auth-shell">
      <aside className="auth-aside">
        <a className="brand" href="/" aria-label="SentinelPay home">
          <span className="brand-mark" aria-hidden="true">S</span>
          <span className="brand-name">sentinel<span>pay</span></span>
        </a>
        <div className="auth-aside-copy">
          <p className="eyebrow">MERCHANT SECURITY</p>
          <h1>Trust every transaction.</h1>
          <p>Access your payment security workspace. No payment or risk data is shown until those services are connected.</p>
        </div>
        <span className="auth-aside-foot">SENTINELPAY <span>·</span> PHASE 2</span>
      </aside>
      <section className="auth-main" aria-labelledby="auth-title">
        <div className="auth-card">
          <p className="eyebrow">WELCOME BACK</p>
          <h2 id="auth-title">Sign in to SentinelPay</h2>
          <p className="auth-intro">Use your merchant account credentials.</p>
          <AuthForm mode="login" />
          <p className="auth-switch">New to SentinelPay? <a href="/register">Create an account</a></p>
        </div>
      </section>
    </main>
  );
}