import { ethers, network } from "hardhat";

async function main() {
  const expectedChainId = 11155111n;
  const actualChainId = BigInt(network.config.chainId ?? 0);
  if (network.name !== "sepolia" || actualChainId !== expectedChainId) {
    throw new Error("Deployment is restricted to Sepolia (chain ID 11155111).");
  }

  const authorizer = process.env.AUTHORIZER_ADDRESS;
  if (!authorizer || !ethers.isAddress(authorizer) || authorizer === ethers.ZeroAddress) {
    throw new Error("Set AUTHORIZER_ADDRESS to the dedicated EIP-712 signing wallet.");
  }

  const [deployer] = await ethers.getSigners();
  if (!deployer) throw new Error("Set DEPLOYER_PRIVATE_KEY for a funded Sepolia deployment wallet.");

  const factory = await ethers.getContractFactory("SentinelEscrow");
  const escrow = await factory.deploy(deployer.address, authorizer);
  await escrow.waitForDeployment();

  const address = await escrow.getAddress();
  console.log(`SentinelEscrow deployed to ${address}`);
  console.log(`Chain ID: ${actualChainId}`);
  console.log(`Owner: ${deployer.address}`);
  console.log(`Authorizer: ${authorizer}`);
}

main().catch((error: unknown) => {
  console.error(error);
  process.exitCode = 1;
});