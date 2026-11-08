import type { Metadata } from "next";
import { AuthForm } from "@/components/auth-form";

export const metadata: Metadata = {
  title: "Create merchant account | SentinelPay",
};

export default function RegisterPage() {
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
          <p>Build your payment security workspace. Testnet-only capabilities are clearly identified while integrations are in development.</p>
        </div>
        <span className="auth-aside-foot">SENTINELPAY <span>·</span> PHASE 2</span>
      </aside>
      <section className="auth-main" aria-labelledby="auth-title">
        <div className="auth-card">
          <p className="eyebrow">GET STARTED</p>
          <h2 id="auth-title">Create your account</h2>
          <p className="auth-intro">Register a merchant workspace to continue.</p>
          <AuthForm mode="register" />
          <p className="auth-switch">Already registered? <a href="/login">Sign in</a></p>
        </div>
      </section>
    </main>
  );
}