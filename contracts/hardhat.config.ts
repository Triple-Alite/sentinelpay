import { HardhatUserConfig } from "hardhat/config";
import "@nomicfoundation/hardhat-toolbox";
import "dotenv/config";

const privateKey = process.env.DEPLOYER_PRIVATE_KEY;
const rpcUrl = process.env.RPC_URL;
const sepoliaAccounts = privateKey ? [privateKey] : [];

const config: HardhatUserConfig = {
  solidity: {
    version: "0.8.26",
    settings: {
      optimizer: { enabled: true, runs: 200 },
      viaIR: true,
      evmVersion: "cancun",
    },
  },
  networks: {
    localhost: {
      url: "http://127.0.0.1:8545",
      chainId: 31337,
    },
    sepolia: {
      url: rpcUrl || "https://ethereum-sepolia-rpc.publicnode.com",
      chainId: 11155111,
      accounts: sepoliaAccounts,
    },
  },
  paths: {
    sources: "./contracts",
    tests: "./test",
    cache: "./cache",
    artifacts: "./artifacts",
  },
};

export default config;