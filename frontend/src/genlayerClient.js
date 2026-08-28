import { createClient, chains } from 'genlayer-js';
import { parseGenToWei, formatWeiToGen, WEI_PER_GEN } from './money.js';

export { parseGenToWei, formatWeiToGen, WEI_PER_GEN };

const ZERO = '0x0000000000000000000000000000000000000000';
const rawAddress = (import.meta.env.VITE_CONTRACT_ADDRESS || '').trim();

export const CONTRACT_ADDRESS = rawAddress || ZERO;

export const hasContractAddress = Boolean(
  rawAddress &&
  rawAddress !== ZERO &&
  /^0x[0-9a-fA-F]{40}$/.test(rawAddress)
);

export const studionet = chains.studionet;

export const getReadClient = () => {
  try {
    return createClient({ chain: studionet });
  } catch (err) {
    console.warn('Read client init failed:', err);
    return null;
  }
};

export const getWriteClient = (account) => {
  if (typeof window === 'undefined' || !window.ethereum) {
    throw new Error('MetaMask is required to sign EquiSettle transactions.');
  }
  const client = createClient({
    chain: studionet,
    account,
    provider: window.ethereum,
  });

  // Hotfix: Overwrite prepareTransactionRequest to bypass genlayer-js hardcoded 21,000 gas limit
  const originalPrepare = client.prepareTransactionRequest;
  client.prepareTransactionRequest = async (args) => {
    const req = await originalPrepare.call(client, args);
    return {
      ...req,
      gas: 2000000n,
    };
  };

  // Hotfix: Intercept the RPC call to force MetaMask to use a high gas limit for state-changing contract calls
  const originalRequest = client.request;
  client.request = async (args) => {
    if (args && args.method === 'eth_sendTransaction' && args.params && args.params[0]) {
      args.params[0].gas = '0x1e8480'; // 2,000,000 in hex representation
    }
    return await originalRequest.call(client, args);
  };

  return client;
};

export const parseJsonMaybe = (res) => {
  if (res === null || res === undefined) return res;
  if (typeof res === 'string') {
    try {
      return JSON.parse(res);
    } catch {
      return res;
    }
  }
  return res;
};

export const waitForTx = async (client, hash) => {
  if (!hash) return null;
  if (client && typeof client.waitForTransactionReceipt === 'function') {
    try {
      return await client.waitForTransactionReceipt({
        hash,
        status: 'FINALIZED',
        retries: 30,
        interval: 2000,
      });
    } catch (err) {
      console.warn('waitForTransactionReceipt error:', err);
    }
  }
  return hash;
};
