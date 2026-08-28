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

  // Hotfix: Proxy window.ethereum to override the gas limit parameter for eth_sendTransaction.
  // This is required because genlayer-js copies methods by spreading/extending them internally,
  // making instance-level overrides on the returned client ineffective inside library closures.
  const customProvider = new Proxy(window.ethereum, {
    get(target, prop, receiver) {
      if (prop === 'request') {
        return async (args) => {
          if (args && args.method === 'eth_sendTransaction' && args.params && args.params[0]) {
            args.params[0].gas = '0x1e8480'; // Force 2,000,000 gas limit in hex to override library's hardcoded 21,000 gas
          }
          return await target.request(args);
        };
      }
      const val = Reflect.get(target, prop, receiver);
      return typeof val === 'function' ? val.bind(target) : val;
    }
  });

  return createClient({
    chain: studionet,
    account,
    provider: customProvider,
  });
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
