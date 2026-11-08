import { expect } from "chai";
import { ethers } from "hardhat";
import { SentinelEscrow, MockToken } from "../typechain-types";

const authorizationTypes = {
  ReleaseAuthorization: [
    { name: "paymentId", type: "bytes32" },
    { name: "referenceHash", type: "bytes32" },
    { name: "merchant", type: "address" },
    { name: "customer", type: "address" },
    { name: "token", type: "address" },
    { name: "amount", type: "uint256" },
    { name: "decision", type: "uint8" },
    { name: "expiration", type: "uint64" },
    { name: "chainId", type: "uint256" },
    { name: "contractAddress", type: "address" },
    { name: "nonce", type: "uint256" },
  ],
};

describe("SentinelEscrow", function () {
  let escrow: SentinelEscrow;
  let token: MockToken;
  let owner: Awaited<ReturnType<typeof ethers.getSigners>>[number];
  let merchant: Awaited<ReturnType<typeof ethers.getSigners>>[number];
  let customer: Awaited<ReturnType<typeof ethers.getSigners>>[number];
  let authorizer: Awaited<ReturnType<typeof ethers.getSigners>>[number];
  let other: Awaited<ReturnType<typeof ethers.getSigners>>[number];

  async function futureExpiry(seconds = 3600): Promise<bigint> {
    const block = await ethers.provider.getBlock("latest");
    return BigInt(block!.timestamp + seconds);
  }

  async function createNativePayment(paymentId: string, amount = ethers.parseEther("1")) {
    const expiry = await futureExpiry();
    const referenceHash = ethers.keccak256(ethers.toUtf8Bytes(`reference-${paymentId}`));
    await escrow.connect(merchant).createPayment(paymentId, referenceHash, ethers.ZeroAddress, amount, expiry);
    await escrow.connect(customer).depositNative(paymentId, { value: amount });
    return { expiry, referenceHash, amount };
  }

  async function signRelease(
    paymentId: string,
    values: { expiry: bigint; referenceHash: string; amount: bigint; token?: string; nonce?: bigint },
    signer = authorizer,
  ) {
    const chain = await ethers.provider.getNetwork();
    const contractAddress = await escrow.getAddress();
    const expiration = await futureExpiry(1800);
    const domain = {
      name: "SentinelEscrow",
      version: "1",
      chainId: chain.chainId,
      verifyingContract: contractAddress,
    };
    const value = {
      paymentId,
      referenceHash: values.referenceHash,
      merchant: merchant.address,
      customer: customer.address,
      token: values.token ?? ethers.ZeroAddress,
      amount: values.amount,
      decision: 0,
      expiration,
      chainId: chain.chainId,
      contractAddress,
      nonce: values.nonce ?? 0n,
    };
    const signature = await signer.signTypedData(domain, authorizationTypes, value);
    return { expiration, nonce: value.nonce, signature };
  }

  beforeEach(async function () {
    [owner, merchant, customer, authorizer, other] = await ethers.getSigners();
    const escrowFactory = await ethers.getContractFactory("SentinelEscrow");
    escrow = await escrowFactory.deploy(owner.address, authorizer.address) as SentinelEscrow;
    const tokenFactory = await ethers.getContractFactory("MockToken");
    token = await tokenFactory.deploy() as MockToken;
    await escrow.connect(owner).setTokenAllowed(await token.getAddress(), true);
    await token.connect(owner).transfer(customer.address, ethers.parseEther("10"));
  });

  it("creates, deposits, assesses, and releases native escrow with a valid signature", async function () {
    const paymentId = ethers.keccak256(ethers.toUtf8Bytes("native-payment"));
    const values = await createNativePayment(paymentId);
    await escrow.connect(authorizer).assessPayment(paymentId, 0);
    const authorization = await signRelease(paymentId, values);

    await expect(
      escrow.connect(merchant).releasePayment(paymentId, authorization.expiration, authorization.nonce, authorization.signature),
    ).to.emit(escrow, "PaymentReleased").withArgs(paymentId, merchant.address, values.amount);
    expect(await escrow.totalEscrowed(ethers.ZeroAddress)).to.equal(0);
    expect((await escrow.payments(paymentId)).state).to.equal(5);
  });

  it("rejects invalid signatures, wrong callers, and replayed authorizations", async function () {
    const paymentId = ethers.keccak256(ethers.toUtf8Bytes("signature-payment"));
    const values = await createNativePayment(paymentId);
    await escrow.connect(authorizer).assessPayment(paymentId, 0);

    const badSignature = await signRelease(paymentId, values, other);
    await expect(
      escrow.connect(merchant).releasePayment(paymentId, badSignature.expiration, badSignature.nonce, badSignature.signature),
    ).to.be.revertedWithCustomError(escrow, "InvalidAuthorization");

    const authorization = await signRelease(paymentId, values);
    await expect(
      escrow.connect(other).releasePayment(paymentId, authorization.expiration, authorization.nonce, authorization.signature),
    ).to.be.revertedWithCustomError(escrow, "Unauthorized");

    await escrow.connect(merchant).releasePayment(paymentId, authorization.expiration, authorization.nonce, authorization.signature);
    await expect(
      escrow.connect(merchant).releasePayment(paymentId, authorization.expiration, authorization.nonce, authorization.signature),
    ).to.be.revertedWithCustomError(escrow, "InvalidState");
  });

  it("keeps review and blocked transactions in escrow", async function () {
    const paymentId = ethers.keccak256(ethers.toUtf8Bytes("held-payment"));
    const values = await createNativePayment(paymentId);
    await escrow.connect(authorizer).assessPayment(paymentId, 1);
    expect((await escrow.payments(paymentId)).state).to.equal(4);
    const authorization = await signRelease(paymentId, values);
    await expect(
      escrow.connect(merchant).releasePayment(paymentId, authorization.expiration, authorization.nonce, authorization.signature),
    ).to.be.revertedWithCustomError(escrow, "InvalidState");
    expect(await escrow.totalEscrowed(ethers.ZeroAddress)).to.equal(values.amount);
    await escrow.connect(owner).resolveReview(paymentId, false);
    expect((await escrow.payments(paymentId)).decision).to.equal(2);
  });

  it("accepts only allowlisted ERC-20 deposits and returns the held token on refund", async function () {
    const paymentId = ethers.keccak256(ethers.toUtf8Bytes("token-payment"));
    const amount = ethers.parseEther("2");
    const expiry = await futureExpiry();
    const referenceHash = ethers.keccak256(ethers.toUtf8Bytes("token-reference"));
    const tokenAddress = await token.getAddress();
    await escrow.connect(merchant).createPayment(paymentId, referenceHash, tokenAddress, amount, expiry);
    await token.connect(customer).approve(await escrow.getAddress(), amount);
    await escrow.connect(customer).depositToken(paymentId);
    expect(await escrow.totalEscrowed(tokenAddress)).to.equal(amount);

    await expect(escrow.connect(other).refundPayment(paymentId)).to.be.revertedWithCustomError(escrow, "RefundUnavailable");
    const before = await token.balanceOf(customer.address);
    await escrow.connect(owner).refundPayment(paymentId);
    expect(await token.balanceOf(customer.address)).to.equal(before + amount);
    expect(await escrow.totalEscrowed(tokenAddress)).to.equal(0);
  });

  it("prevents incorrect deposits, expires unpaid requests, and honors emergency pause", async function () {
    const paymentId = ethers.keccak256(ethers.toUtf8Bytes("expiry-payment"));
    const expiry = await futureExpiry(60);
    const referenceHash = ethers.keccak256(ethers.toUtf8Bytes("expiry-reference"));
    const amount = ethers.parseEther("1");
    await escrow.connect(merchant).createPayment(paymentId, referenceHash, ethers.ZeroAddress, amount, expiry);
    await expect(escrow.connect(customer).depositNative(paymentId, { value: amount - 1n })).to.be.revertedWithCustomError(escrow, "InvalidAmount");
    await ethers.provider.send("evm_increaseTime", [61]);
    await ethers.provider.send("evm_mine", []);
    await escrow.connect(other).expirePayment(paymentId);
    expect((await escrow.payments(paymentId)).state).to.equal(7);

    await escrow.connect(owner).pause();
    const nextPayment = ethers.keccak256(ethers.toUtf8Bytes("paused-payment"));
    await expect(
      escrow.connect(merchant).createPayment(nextPayment, referenceHash, ethers.ZeroAddress, amount, await futureExpiry()),
    ).to.be.revertedWithCustomError(escrow, "EnforcedPause");
    await escrow.connect(owner).unpause();
  });
});