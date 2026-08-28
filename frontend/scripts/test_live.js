import { createClient, chains } from 'genlayer-js';

const CONTRACT_ADDRESS = '0x8046D9fc4309eA2ed4d842774AC9F74F835D3150';
const DUMMY_ACCOUNT = '0x90F8bf6A479f320ead074411a4B0e7944Ecf8239'; // Standard dummy address

async function main() {
  console.log("Connecting to GenLayer StudioNet RPC...");
  // Pass a dummy account so the 'from' field is populated in read contract calls
  const client = createClient({ 
    chain: chains.studionet,
    account: DUMMY_ACCOUNT
  });
  
  console.log("Calling view method 'get_owner'...");
  try {
    const owner = await client.readContract({
      address: CONTRACT_ADDRESS,
      functionName: 'get_owner',
    });
    console.log(">>> SUCCESS! Deployed Contract Owner:", owner);
  } catch (err) {
    console.error(">>> ERROR reading get_owner:", err.message || err);
  }

  console.log("Calling view method 'get_count'...");
  try {
    const count = await client.readContract({
      address: CONTRACT_ADDRESS,
      functionName: 'get_count',
    });
    console.log(">>> SUCCESS! Total Transactions Locked:", Number(count));
  } catch (err) {
    console.error(">>> ERROR reading get_count:", err.message || err);
  }
}

main();
