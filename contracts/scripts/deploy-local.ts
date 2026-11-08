import { ethers, network } from "hardhat";

async function main() {
  const expectedChainId = 31337n;
  const actualChainId = BigInt(network.config.chainId ?? 0);
  if (network.name !== "localhost" || actualChainId !== expectedChainId) {
    throw new Error("Local deployment is restricted to Hardhat chain ID 31337.");
  }

  const [owner, defaultAuthorizer] = await ethers.getSigners();
  if (!owner || !defaultAuthorizer) {
    throw new Error("Start a Hardhat node with unlocked local accounts before deploying.");
  }
  const authorizer = process.env.AUTHORIZER_ADDRESS ?? defaultAuthorizer.address;
  if (!ethers.isAddress(authorizer) || authorizer === ethers.ZeroAddress) {
    throw new Error("AUTHORIZER_ADDRESS must be a non-zero local authorizer address.");
  }

  const factory = await ethers.getContractFactory("SentinelEscrow", owner);
  const escrow = await factory.deploy(owner.address, authorizer);
  await escrow.waitForDeployment();

  console.log(`SentinelEscrow deployed to ${await escrow.getAddress()}`);
  console.log(`Chain ID: ${actualChainId}`);
  console.log(`Owner: ${owner.address}`);
  console.log(`Authorizer: ${authorizer}`);
}

main().catch((error: unknown) => {
  console.error(error);
  process.exitCode = 1;
});
