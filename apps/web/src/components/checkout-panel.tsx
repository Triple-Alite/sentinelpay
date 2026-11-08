"use client";

import { useEffect, useState } from "react";
import { encodeDepositNativeData, getInjectedWallet, parseEtherAmount } from "@/lib/escrow";

type CheckoutPayment = {
  reference: string;
  merchant_name: string;
  description: string;
  amount: string;
  currency: string;
  chain_id: number;
  status: string;
  onchain_state: string;
  onchain_payment_id: string | null;
  expires_at: string;
};

type CheckoutConfig = {
  chain_id: number;
  escrow_address: string | null;
  escrow_deployed: boolean;
  checkout_enabled: boolean;
};

type WalletState = { address: string; chainId: number } | null;
type WalletProvider = {
  request: (arguments_: { method: string; params?: unknown[] }) => Promise<unknown>;
  on?: (event: "accountsChanged" | "chainChanged", listener: () => void) => void;
  removeListener?: (event: "accountsChanged" | "chainChanged", listener: () => void) => void;
};

declare global {
  interface Window {
    ethereum?: WalletProvider;
  }
}

export function CheckoutPanel({ reference }: { reference: string }) {
  const [payment, setPayment] = useState<CheckoutPayment | null>(null);
  const [loadError, setLoadError] = useState("");
  const [chainConfig, setChainConfig] = useState<CheckoutConfig | null>(null);
  const [chainConfigError, setChainConfigError] = useState("");
  const [wallet, setWallet] = useState<WalletState>(null);
  const [walletError, setWalletError] = useState("");
  const [depositing, setDepositing] = useState(false);

  useEffect(() => {
    const provider = window.ethereum;
    if (!provider?.on) return;
    const activeProvider = provider;

    async function refreshWallet() {
      try {
        const [accounts, chain] = await Promise.all([
          activeProvider.request({ method: "eth_accounts" }),
          activeProvider.request({ method: "eth_chainId" }),
        ]);
        if (Array.isArray(accounts) && typeof accounts[0] === "string" && typeof chain === "string") {
          setWallet({ address: accounts[0], chainId: Number.parseInt(chain, 16) });
        } else {
          setWallet(null);
        }
      } catch {
        setWallet(null);
      }
    }

    const handleWalletChange = () => void refreshWallet();
    activeProvider.on?.("accountsChanged", handleWalletChange);
    activeProvider.on?.("chainChanged", handleWalletChange);
    return () => {
      activeProvider.removeListener?.("accountsChanged", handleWalletChange);
      activeProvider.removeListener?.("chainChanged", handleWalletChange);
    };
  }, []);

  useEffect(() => {
    const apiUrl = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
    const controller = new AbortController();

    async function loadPayment() {
      try {
        const response = await fetch(`${apiUrl}/api/v1/payments/checkout/${encodeURIComponent(reference)}`, {
          cache: "no-store",
          signal: controller.signal,
        });
        if (!response.ok) {
          if (response.status === 404) setLoadError("This payment request was not found.");
          else setLoadError("Payment details are temporarily unavailable.");
          return;
        }
        setPayment(await response.json() as CheckoutPayment);
        setLoadError("");
      } catch {
        if (!controller.signal.aborted) setLoadError("Could not reach SentinelPay. Try again when the service is available.");
      }
    }

    void loadPayment();
    const intervalId = window.setInterval(loadPayment, 10000);
    return () => {
      controller.abort();
      window.clearInterval(intervalId);
    };
  }, [reference]);

  useEffect(() => {
    const apiUrl = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
    const controller = new AbortController();

    async function loadChainConfig() {
      try {
        const response = await fetch(`${apiUrl}/api/v1/chain/checkout-config`, {
          cache: "no-store",
          signal: controller.signal,
        });
        if (!response.ok) {
          setChainConfig(null);
          setChainConfigError("The network readiness check is unavailable.");
          return;
        }
        setChainConfig(await response.json() as CheckoutConfig);
        setChainConfigError("");
      } catch {
        if (!controller.signal.aborted) {
          setChainConfig(null);
          setChainConfigError("Could not verify the escrow network.");
        }
      }
    }

    void loadChainConfig();
    const intervalId = window.setInterval(loadChainConfig, 10000);
    return () => {
      controller.abort();
      window.clearInterval(intervalId);
    };
  }, []);

  async function connectWallet() {
    setWalletError("");
    if (!window.ethereum) {
      setWalletError("No injected wallet was found. Install MetaMask to connect a test wallet.");
      return;
    }
    try {
      const accounts = await window.ethereum.request({ method: "eth_requestAccounts" });
      const chain = await window.ethereum.request({ method: "eth_chainId" });
      if (!Array.isArray(accounts) || typeof accounts[0] !== "string" || typeof chain !== "string") {
        throw new Error("Wallet returned an invalid account or network.");
      }
      setWallet({ address: accounts[0], chainId: Number.parseInt(chain, 16) });
    } catch (error) {
      setWalletError(error instanceof Error ? error.message : "Wallet connection was not completed.");
    }
  }

  async function switchToPaymentChain() {
    const provider = getInjectedWallet();
    if (!provider) return;
    setWalletError("");
    const targetChainId = chainConfig?.chain_id ?? payment?.chain_id ?? 11155111;
    const isLocalHardhat = targetChainId === 31337;
    try {
      await provider.request({
        method: "wallet_switchEthereumChain",
        params: [{ chainId: `0x${targetChainId.toString(16)}` }],
      });
      const [accounts, chain] = await Promise.all([
        provider.request({ method: "eth_accounts" }),
        provider.request({ method: "eth_chainId" }),
      ]);
      if (!Array.isArray(accounts) || typeof accounts[0] !== "string" || typeof chain !== "string") {
        throw new Error("Wallet returned an invalid account or network.");
      }
      setWallet({ address: accounts[0], chainId: Number.parseInt(chain, 16) });
    } catch (error) {
      const errorCode = typeof error === "object" && error !== null && "code" in error ? error.code : undefined;
      if (errorCode === 4902) {
        try {
          await provider.request({
            method: "wallet_addEthereumChain",
            params: [{
              chainId: `0x${targetChainId.toString(16)}`,
              chainName: isLocalHardhat ? "Hardhat Local" : "Sepolia",
              nativeCurrency: { name: isLocalHardhat ? "Hardhat ETH" : "Sepolia ETH", symbol: "ETH", decimals: 18 },
              rpcUrls: [isLocalHardhat ? "http://127.0.0.1:8545" : "https://ethereum-sepolia-rpc.publicnode.com"],
              ...(isLocalHardhat ? {} : { blockExplorerUrls: ["https://sepolia.etherscan.io"] }),
            }],
          });
          const [accounts, chain] = await Promise.all([
            provider.request({ method: "eth_accounts" }),
            provider.request({ method: "eth_chainId" }),
          ]);
          if (!Array.isArray(accounts) || typeof accounts[0] !== "string" || typeof chain !== "string") {
            throw new Error("Wallet returned an invalid account or network.");
          }
          setWallet({ address: accounts[0], chainId: Number.parseInt(chain, 16) });
          return;
        } catch (addError) {
          setWalletError(addError instanceof Error ? addError.message : "Could not add Sepolia to this wallet.");
          return;
        }
      }
      setWalletError(error instanceof Error ? error.message : "Could not switch to Sepolia.");
    }
  }

  async function depositToEscrow() {
    if (!payment || !chainConfig?.checkout_enabled || !chainConfig.escrow_address || !payment.onchain_payment_id) {
      setWalletError("The verified escrow is not ready for this payment.");
      return;
    }
    const provider = getInjectedWallet();
    if (!provider) {
      setWalletError("Install or unlock an injected wallet to deposit.");
      return;
    }

    setWalletError("");
    setDepositing(true);
    try {
      const accounts = await provider.request({ method: "eth_requestAccounts" });
      const chain = await provider.request({ method: "eth_chainId" });
      if (!Array.isArray(accounts) || typeof accounts[0] !== "string" || typeof chain !== "string") {
        throw new Error("Wallet returned an invalid account or network.");
      }
      if (Number.parseInt(chain, 16) !== payment.chain_id) {
        throw new Error(`Switch your wallet to chain ${payment.chain_id} before depositing.`);
      }
      const transactionHash = await provider.request({
        method: "eth_sendTransaction",
        params: [{
          from: accounts[0],
          to: chainConfig.escrow_address,
          data: encodeDepositNativeData(payment.onchain_payment_id),
          value: `0x${parseEtherAmount(payment.amount).toString(16)}`,
        }],
      });
      if (typeof transactionHash !== "string" || !/^0x[0-9a-fA-F]{64}$/.test(transactionHash)) {
        throw new Error("Wallet did not return a valid transaction hash.");
      }
      let receipt: unknown = null;
      for (let attempt = 0; attempt < 30; attempt += 1) {
        receipt = await provider.request({ method: "eth_getTransactionReceipt", params: [transactionHash] });
        if (receipt) break;
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
      }
      if (!receipt || typeof receipt !== "object" || !("status" in receipt)) {
        throw new Error(`Deposit is still pending. Transaction: ${transactionHash}`);
      }
      if (receipt.status !== "0x1") throw new Error(`Deposit transaction reverted: ${transactionHash}`);
      const apiUrl = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
      const response = await fetch(`${apiUrl}/api/v1/payments/checkout/${encodeURIComponent(reference)}/deposit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ operation: "DEPOSIT", transaction_hash: transactionHash }),
      });
      const result = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(result?.detail ?? "Deposit was sent but could not yet be confirmed by SentinelPay.");
      }
      setPayment({ ...payment, status: "RISK_ASSESSMENT", onchain_state: "DEPOSITED" });
    } catch (error) {
      setWalletError(error instanceof Error ? error.message : "Could not complete the deposit.");
    } finally {
      setDepositing(false);
    }
  }

  if (loadError) {
    return <main className="checkout-shell"><section className="checkout-panel"><p className="eyebrow">SENTINELPAY CHECKOUT</p><h1>Checkout unavailable</h1><p role="alert">{loadError}</p><a href="/">Return to SentinelPay</a></section></main>;
  }
  if (!payment) {
    return <main className="checkout-shell"><section className="checkout-panel"><p className="eyebrow">SENTINELPAY CHECKOUT</p><h1>Loading payment details</h1><div className="loading-line" aria-hidden="true" /></section></main>;
  }

  const isSepolia = payment.chain_id === 11155111;
  const isPending = payment.status === "CREATED" || payment.status === "AWAITING_PAYMENT";
  const isEscrowReady = Boolean(
    chainConfig?.checkout_enabled && chainConfig.chain_id === payment.chain_id && chainConfig.escrow_address,
  );
  const canDeposit = isEscrowReady
    && payment.status === "AWAITING_PAYMENT"
    && payment.onchain_state === "CREATED"
    && Boolean(payment.onchain_payment_id);

  return (
    <main className="checkout-shell">
      <section className="checkout-panel" aria-labelledby="checkout-title">
        <a className="brand" href="/" aria-label="SentinelPay home">
          <span className="brand-mark" aria-hidden="true">S</span>
          <span className="brand-name">sentinel<span>pay</span></span>
        </a>
        <p className="eyebrow checkout-kicker">SECURE PAYMENT REQUEST</p>
        <h1 id="checkout-title">{payment.merchant_name}</h1>
        <p className="checkout-description">{payment.description}</p>
        <div className="checkout-amount"><span>Amount due</span><strong>{payment.amount} <small>{payment.currency}</small></strong></div>
        <dl className="checkout-details">
          <div><dt>Network</dt><dd>{isSepolia ? "Sepolia testnet" : `Chain ${payment.chain_id}`}</dd></div>
          <div><dt>Request status</dt><dd>{payment.status.replaceAll("_", " ")}</dd></div>
          <div><dt>Escrow status</dt><dd>{payment.onchain_state.replaceAll("_", " ")}</dd></div>
          <div><dt>Expires</dt><dd>{new Date(payment.expires_at).toLocaleString()}</dd></div>
        </dl>
        <div className="checkout-security"><span className="status-dot status-dot-amber" /><span>Checkout is read-only until this network's escrow deployment and release flow are verified.</span></div>
        {payment.status === "EXPIRED" || payment.status === "CANCELLED" ? (
          <p className="checkout-closed">This payment request is no longer available.</p>
        ) : (
          <>
            <button className="auth-submit wallet-button" type="button" onClick={connectWallet}>
              {wallet ? "Wallet connected" : "Connect MetaMask"}
            </button>
            {wallet && (
              <p className="wallet-detail" role="status">
                {wallet.address.slice(0, 6)}...{wallet.address.slice(-4)} · {wallet.chainId === payment.chain_id ? "Sepolia" : `Wrong network (${wallet.chainId})`}
              </p>
            )}
            {wallet && wallet.chainId !== payment.chain_id && (
              <button className="auth-submit wallet-button" type="button" onClick={switchToPaymentChain}>
                Switch to {isSepolia ? "Sepolia" : `chain ${payment.chain_id}`}
              </button>
            )}
            {walletError && <p className="auth-error" role="alert">{walletError}</p>}
            {chainConfigError ? <p className="wallet-detail" role="status">{chainConfigError}</p> : chainConfig && !isEscrowReady ? (
              <p className="wallet-detail" role="status">
                {chainConfig.chain_id !== payment.chain_id
                  ? `The API is connected to chain ${chainConfig.chain_id}, not this request's chain.`
                  : "No verified escrow deployment is available for this network."}
              </p>
            ) : null}
            <button className="payment-disabled" type="button" disabled aria-disabled="true">
              {isPending ? isEscrowReady ? "Payment flow awaits lifecycle verification" : "Payment disabled: escrow is not verified" : `Request ${payment.status.toLowerCase()}`}
            </button>
            {canDeposit && (
              <button className="auth-submit wallet-button" type="button" onClick={depositToEscrow} disabled={depositing || !wallet || wallet.chainId !== payment.chain_id}>
                {depositing ? "Confirming deposit..." : `Deposit ${payment.amount} ETH`}
              </button>
            )}
          </>
        )}
      </section>
      <p className="checkout-footer">SentinelPay <span>·</span> Sepolia testnet only</p>
    </main>
  );
}