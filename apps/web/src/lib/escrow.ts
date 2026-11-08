export type Eip1193Provider = {
  request: (arguments_: { method: string; params?: unknown[] }) => Promise<unknown>;
};

const CREATE_PAYMENT_SELECTOR = "0x0e8aa851";
const DEPOSIT_NATIVE_SELECTOR = "0x42ef5fbb";
const RELEASE_PAYMENT_SELECTOR = "0xea9f5a0a";
const BYTES32_PATTERN = /^0x[0-9a-fA-F]{64}$/;

function encodeUint256(value: bigint): string {
  if (value < BigInt(0) || value >= BigInt(1) << BigInt(256)) throw new Error("Integer is outside the uint256 range.");
  return value.toString(16).padStart(64, "0");
}

export function parseEtherAmount(value: string): bigint {
  const match = /^(0|[1-9]\d*)(?:\.(\d{1,18}))?$/.exec(value);
  if (!match) throw new Error("Enter a valid ETH amount with up to 18 decimal places.");
  const whole = BigInt(match[1]);
  const fraction = BigInt((match[2] ?? "").padEnd(18, "0") || "0");
  const amount = whole * BigInt(10) ** BigInt(18) + fraction;
  if (amount === BigInt(0)) throw new Error("Payment amount must be greater than zero.");
  return amount;
}

export function encodeCreatePaymentData(
  paymentId: string,
  referenceHash: string,
  amountWei: bigint,
  expiresAt: bigint,
): string {
  if (!BYTES32_PATTERN.test(paymentId) || !BYTES32_PATTERN.test(referenceHash)) {
    throw new Error("Payment identifier is invalid.");
  }
  if (expiresAt < BigInt(0) || expiresAt >= BigInt(1) << BigInt(64)) throw new Error("Expiry is outside the uint64 range.");
    return `${CREATE_PAYMENT_SELECTOR}${paymentId.slice(2)}${referenceHash.slice(2)}${"0".repeat(64)}${encodeUint256(amountWei)}${encodeUint256(expiresAt)}`;
}

export function encodeDepositNativeData(paymentId: string): string {
  if (!BYTES32_PATTERN.test(paymentId)) throw new Error("Payment identifier is invalid.");
  return `${DEPOSIT_NATIVE_SELECTOR}${paymentId.slice(2)}`;
}

export function encodeReleasePaymentData(
  paymentId: string,
  expiration: bigint,
  nonce: bigint,
  signature: string,
): string {
  if (!BYTES32_PATTERN.test(paymentId)) throw new Error("Payment identifier is invalid.");
  if (expiration < BigInt(0) || expiration >= BigInt(1) << BigInt(64)) {
    throw new Error("Authorization expiry is outside the uint64 range.");
  }
  if (!/^0x(?:[0-9a-fA-F]{2})+$/.test(signature)) throw new Error("Release signature is invalid.");
  const signatureBytes = signature.slice(2);
  const length = signatureBytes.length / 2;
  const paddedSignature = signatureBytes.padEnd(Math.ceil(length / 32) * 64, "0");
  return `${RELEASE_PAYMENT_SELECTOR}${paymentId.slice(2)}${encodeUint256(expiration)}${encodeUint256(nonce)}${encodeUint256(BigInt(128))}${encodeUint256(BigInt(length))}${paddedSignature}`;
}

export function getInjectedWallet(): Eip1193Provider | null {
  return (window as Window & { ethereum?: Eip1193Provider }).ethereum ?? null;
}
