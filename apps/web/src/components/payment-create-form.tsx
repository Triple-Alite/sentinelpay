"use client";

import { FormEvent, useEffect, useState } from "react";
import { encodeCreatePaymentData, encodeReleasePaymentData, getInjectedWallet, parseEtherAmount } from "@/lib/escrow";

type CheckoutConfig = {
  chain_id: number;
  escrow_address: string | null;
  checkout_enabled: boolean;
};

type CreatedPayment = {
  id: string;
  reference: string;
  description: string;
  amount: string;
  currency: string;
  chain_id: number;
  onchain_payment_id: string;
  onchain_reference_hash: string;
  merchant_wallet_address: string | null;
  onchain_state: string;
  expires_at: string;
  checkout_url: string;
  status: string;
};

export function PaymentCreateForm() {
  const [payment, setPayment] = useState<CreatedPayment | null>(null);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [chainConfig, setChainConfig] = useState<CheckoutConfig | null>(null);
  const [chainConfigLoading, setChainConfigLoading] = useState(true);
  const [onchainStatus, setOnchainStatus] = useState("");

  useEffect(() => {
    const apiUrl = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
    const controller = new AbortController();
    fetch(`${apiUrl}/api/v1/chain/checkout-config`, { cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("Chain readiness could not be verified.");
        setChainConfig(await response.json() as CheckoutConfig);
      })
      .catch(() => {
        if (!controller.signal.aborted) setChainConfig(null);
      })
      .finally(() => {
        if (!controller.signal.aborted) setChainConfigLoading(false);
      });
    return () => controller.abort();
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPayment(null);
    setError("");
    const formData = new FormData(event.currentTarget);
    setSubmitting(true);
    try {
      const apiUrl = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
      const response = await fetch(`${apiUrl}/api/v1/payments`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          amount: String(formData.get("amount") ?? ""),
          currency: "ETH",
          description: String(formData.get("description") ?? "").trim(),
          chain_id: chainConfig?.chain_id ?? Number(process.env.NEXT_PUBLIC_CHAIN_ID || 11155111),
          expires_in_minutes: Number(formData.get("expires_in_minutes") ?? 60),
        }),
      });
      const result = await response.json().catch(() => null);
      if (!response.ok) {
        if (response.status === 401) {
          setError("Sign in with a merchant account before creating a payment request.");
        } else {
          const detail = result?.detail;
          setError(Array.isArray(detail) ? detail[0]?.msg ?? "Check the payment details." : detail ?? "Could not create the payment request.");
        }
        return;
      }
      setPayment(result as CreatedPayment);
      event.currentTarget.reset();
    } catch {
      setError("Could not reach SentinelPay. Check that the API and database are running.");
    } finally {
      setSubmitting(false);
    }
  }

  async function createOnchainPayment() {
    setError("");
    setOnchainStatus("");
    if (!payment || !chainConfig?.checkout_enabled || !chainConfig.escrow_address) {
      setError("A deployed escrow on the configured network is required before creating an on-chain payment.");
      return;
    }
    const wallet = getInjectedWallet();
    if (!wallet) {
      setError("Install or unlock an injected wallet to create the escrow payment.");
      return;
    }

    setSubmitting(true);
    try {
      const accounts = await wallet.request({ method: "eth_requestAccounts" });
      const chain = await wallet.request({ method: "eth_chainId" });
      if (!Array.isArray(accounts) || typeof accounts[0] !== "string" || typeof chain !== "string") {
        throw new Error("Wallet returned an invalid account or network.");
      }
      if (Number.parseInt(chain, 16) !== payment.chain_id) {
        throw new Error(`Switch your wallet to chain ${payment.chain_id} before creating this escrow.`);
      }

      const amountWei = parseEtherAmount(payment.amount);
      const expiresAt = BigInt(Math.floor(new Date(payment.expires_at).getTime() / 1000));
      const data = encodeCreatePaymentData(
        payment.onchain_payment_id,
        payment.onchain_reference_hash,
        amountWei,
        expiresAt,
      );
      const transactionHash = await wallet.request({
        method: "eth_sendTransaction",
        params: [{ from: accounts[0], to: chainConfig.escrow_address, data, value: "0x0" }],
      });
      if (typeof transactionHash !== "string" || !/^0x[0-9a-fA-F]{64}$/.test(transactionHash)) {
        throw new Error("Wallet did not return a valid transaction hash.");
      }

      const apiUrl = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
      const recorded = await fetch(`${apiUrl}/api/v1/payments/${payment.id}/chain-transactions`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ operation: "CREATE_PAYMENT", transaction_hash: transactionHash }),
      });
      if (!recorded.ok) throw new Error("The transaction was sent, but the API could not record it. Contact support with the transaction hash.");
      const transaction = await recorded.json() as { id: string };
      setOnchainStatus("Escrow creation submitted; waiting for confirmation.");
      for (let attempt = 0; attempt < 30; attempt += 1) {
        const refreshed = await fetch(`${apiUrl}/api/v1/payments/${payment.id}/chain-transactions/${transaction.id}/refresh`, {
          method: "POST",
          credentials: "include",
        });
        if (!refreshed.ok) throw new Error("The transaction was submitted, but its confirmation could not be checked.");
        const result = await refreshed.json() as { status: string };
        if (result.status === "MINED") {
          setPayment({ ...payment, onchain_state: "CREATED", status: "AWAITING_PAYMENT" });
          setOnchainStatus("Escrow creation confirmed on-chain.");
          return;
        }
        if (result.status === "FAILED") {
          setPayment({ ...payment, onchain_state: "NOT_CREATED" });
          throw new Error("Escrow creation reverted or did not emit the expected contract event.");
        }
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
      }
      setPayment({ ...payment, onchain_state: "CREATION_PENDING" });
      setOnchainStatus("Still waiting for confirmation. This page will not accept a deposit until creation is confirmed.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not create the escrow payment.");
    } finally {
      setSubmitting(false);
    }
  }

  async function releaseOnchainPayment() {
    setError("");
    setOnchainStatus("");
    if (!payment || !chainConfig?.checkout_enabled || !chainConfig.escrow_address || !payment.merchant_wallet_address) {
      setError("A confirmed merchant wallet and verified escrow are required before release.");
      return;
    }
    const wallet = getInjectedWallet();
    if (!wallet) {
      setError("Install or unlock the merchant wallet to release this payment.");
      return;
    }

    setSubmitting(true);
    try {
      const accounts = await wallet.request({ method: "eth_requestAccounts" });
      const chain = await wallet.request({ method: "eth_chainId" });
      if (!Array.isArray(accounts) || typeof accounts[0] !== "string" || typeof chain !== "string") {
        throw new Error("Wallet returned an invalid account or network.");
      }
      if (accounts[0].toLowerCase() !== payment.merchant_wallet_address.toLowerCase()) {
        throw new Error("Connect the merchant wallet that created this escrow.");
      }
      if (Number.parseInt(chain, 16) !== payment.chain_id) {
        throw new Error(`Switch your wallet to chain ${payment.chain_id} before releasing this payment.`);
      }

      const apiUrl = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
      const authorizationResponse = await fetch(`${apiUrl}/api/v1/payments/${payment.id}/release-authorization`, {
        method: "POST",
        credentials: "include",
      });
      const authorization = await authorizationResponse.json().catch(() => null);
      if (!authorizationResponse.ok) throw new Error(authorization?.detail ?? "Could not authorize this release.");

      const data = encodeReleasePaymentData(
        payment.onchain_payment_id,
        BigInt(authorization.expires_at),
        BigInt(authorization.nonce),
        authorization.signature,
      );
      const transactionHash = await wallet.request({
        method: "eth_sendTransaction",
        params: [{ from: accounts[0], to: chainConfig.escrow_address, data, value: "0x0" }],
      });
      if (typeof transactionHash !== "string" || !/^0x[0-9a-fA-F]{64}$/.test(transactionHash)) {
        throw new Error("Wallet did not return a valid transaction hash.");
      }
      const recorded = await fetch(`${apiUrl}/api/v1/payments/${payment.id}/chain-transactions`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ operation: "RELEASE", transaction_hash: transactionHash }),
      });
      if (!recorded.ok) throw new Error(`Release submitted but not recorded. Transaction: ${transactionHash}`);
      const transaction = await recorded.json() as { id: string };
      setOnchainStatus("Release submitted; waiting for confirmation.");
      for (let attempt = 0; attempt < 30; attempt += 1) {
        const refreshed = await fetch(`${apiUrl}/api/v1/payments/${payment.id}/chain-transactions/${transaction.id}/refresh`, {
          method: "POST",
          credentials: "include",
        });
        if (!refreshed.ok) throw new Error("Release was submitted, but its confirmation could not be checked.");
        const result = await refreshed.json() as { status: string };
        if (result.status === "MINED") {
          setPayment({ ...payment, onchain_state: "RELEASED", status: "COMPLETED" });
          setOnchainStatus("Payment release confirmed on-chain.");
          return;
        }
        if (result.status === "FAILED") throw new Error("Release transaction reverted or did not emit the expected contract event.");
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
      }
      setOnchainStatus(`Release is still pending. Transaction: ${transactionHash}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not release the escrow payment.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="payment-create-layout">
      <form className="payment-form" onSubmit={submit}>
        <label className="auth-field">
          <span>Amount</span>
          <div className="amount-input-wrap">
            <input name="amount" type="number" min="0.000000000000000001" step="0.000000000000000001" inputMode="decimal" required />
            <span>ETH</span>
          </div>
          <small>Sepolia testnet only. No mainnet funds are accepted.</small>
        </label>
        <label className="auth-field">
          <span>Order description</span>
          <input name="description" minLength={1} maxLength={240} placeholder="Order #1001" required />
        </label>
        <label className="auth-field">
          <span>Request expires</span>
          <select name="expires_in_minutes" defaultValue="60">
            <option value="15">15 minutes</option>
            <option value="60">1 hour</option>
            <option value="1440">24 hours</option>
            <option value="10080">7 days</option>
          </select>
        </label>
        {error && <p className="auth-error" role="alert">{error}</p>}
        <button className="auth-submit" type="submit" disabled={submitting}>
          {submitting ? "Creating request..." : "Create payment request"}
        </button>
      </form>

      {payment ? (
        <section className="created-payment" aria-live="polite">
          <p className="eyebrow">REQUEST CREATED</p>
          <h2>{payment.amount} {payment.currency}</h2>
          <p>{payment.description}</p>
          <a className="checkout-link" href={payment.checkout_url}>Open customer checkout</a>
          {payment.onchain_state === "NOT_CREATED" && (
            <button
              className="auth-submit"
              type="button"
              onClick={createOnchainPayment}
              disabled={submitting || chainConfigLoading || !chainConfig?.checkout_enabled}
            >
              {chainConfigLoading ? "Checking escrow network..." : submitting ? "Waiting for wallet..." : "Create escrow on-chain"}
            </button>
          )}
          {payment.status === "APPROVED" && payment.onchain_state === "APPROVED" && (
            <button className="auth-submit" type="button" onClick={releaseOnchainPayment} disabled={submitting || chainConfigLoading || !chainConfig?.checkout_enabled}>
              {submitting ? "Waiting for wallet..." : "Release approved payment"}
            </button>
          )}
          {onchainStatus && <p className="service-state" role="status">{onchainStatus}</p>}
          {error && <p className="auth-error" role="alert">{error}</p>}
          <label className="auth-field checkout-url-field">
            <span>Checkout path</span>
            <input readOnly value={payment.checkout_url} onFocus={(event) => event.currentTarget.select()} />
          </label>
          <span className="service-state"><span className="status-dot status-dot-amber" />{payment.status} · {payment.onchain_state.replaceAll("_", " ")}</span>
        </section>
      ) : (
        <aside className="payment-note">
          <p className="eyebrow">CURRENT CAPABILITIES</p>
          <h2>Request first. Escrow next.</h2>
          <p>Requests are stored in the API and shown on a public checkout page. Wallet deposits and settlement stay disabled until the escrow contract is deployed and verified.</p>
        </aside>
      )}
    </div>
  );
}