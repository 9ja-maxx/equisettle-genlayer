import React, { useState, useEffect, useCallback } from 'react';
import { 
  Shield, Plus, ArrowRight, Scale, ThumbsUp, Trash, 
  RefreshCw, Lock, Unlock, AlertTriangle, Link2, ExternalLink 
} from 'lucide-react';
import { 
  getReadClient, getWriteClient, CONTRACT_ADDRESS, hasContractAddress,
  parseJsonMaybe, parseGenToWei, formatWeiToGen, waitForTx 
} from './genlayerClient.js';
import { DEAL_CATEGORIES } from './data/categories.js';

export default function App() {
  const [account, setAccount] = useState('');
  const [transactions, setTransactions] = useState([]);
  const [selectedTxId, setSelectedTxId] = useState('');
  const [selectedTx, setSelectedTx] = useState(null);
  const [statusFilter, setStatusFilter] = useState('');
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [successMessage, setSuccessMessage] = useState('');

  // Creation state
  const [sellerAddr, setSellerAddr] = useState('');
  const [category, setCategory] = useState(DEAL_CATEGORIES[0].id);
  const [description, setDescription] = useState('');
  const [amountGen, setAmountGen] = useState('');
  const [deadlineHrs, setDeadlineHrs] = useState('24');

  // Evidence states
  const [sellerUrls, setSellerUrls] = useState(['']);
  const [sellerStatement, setSellerStatement] = useState('');
  const [buyerUrls, setBuyerUrls] = useState(['']);
  const [buyerStatement, setBuyerStatement] = useState('');

  // Auto-fill template description when category changes
  useEffect(() => {
    const selectedCat = DEAL_CATEGORIES.find(c => c.id === category);
    if (selectedCat) {
      setDescription(selectedCat.placeholder);
    }
  }, [category]);

  const connectWallet = async () => {
    if (typeof window !== 'undefined' && window.ethereum) {
      try {
        const accs = await window.ethereum.request({ method: 'eth_requestAccounts' });
        setAccount(accs[0]);
        clearMessages();
      } catch (err) {
        setErrorMessage(err.message || 'Wallet connection failed');
      }
    } else {
      setErrorMessage('MetaMask was not found. Please install MetaMask to sign transactions.');
    }
  };

  const clearMessages = () => {
    setErrorMessage('');
    setSuccessMessage('');
  };

  const fetchTransactions = useCallback(async () => {
    const reader = getReadClient();
    if (!reader) return;
    try {
      const rawList = await reader.readContract({
        address: CONTRACT_ADDRESS,
        functionName: 'list_transactions',
        args: [statusFilter]
      });
      const parsed = parseJsonMaybe(rawList) || [];
      setTransactions(parsed.reverse());
    } catch (err) {
      console.error('Failed to list transactions:', err);
    }
  }, [statusFilter]);

  const fetchTxDetail = useCallback(async (txId) => {
    if (!txId) return;
    const reader = getReadClient();
    if (!reader) return;
    try {
      const rawDetail = await reader.readContract({
        address: CONTRACT_ADDRESS,
        functionName: 'get_transaction',
        args: [txId]
      });
      const parsed = parseJsonMaybe(rawDetail);
      setSelectedTx(parsed);
    } catch (err) {
      console.error('Failed to fetch tx detail:', err);
    }
  }, []);

  useEffect(() => {
    fetchTransactions();
  }, [fetchTransactions]);

  useEffect(() => {
    if (selectedTxId) {
      fetchTxDetail(selectedTxId);
      const interval = setInterval(() => fetchTxDetail(selectedTxId), 5000);
      return () => clearInterval(interval);
    } else {
      setSelectedTx(null);
    }
  }, [selectedTxId, fetchTxDetail]);

  const handleCreateEscrow = async (e) => {
    e.preventDefault();
    clearMessages();
    if (!account) return setErrorMessage('Connect your wallet first.');
    if (!sellerAddr) return setErrorMessage('Seller address is required.');
    const wei = parseGenToWei(amountGen);
    if (!amountGen || wei <= 0n) return setErrorMessage('Enter a valid positive GEN amount.');

    setLoading(true);
    try {
      const writer = getWriteClient(account);
      const nowSeconds = BigInt(Date.now()) / 1000n;
      const deadlineSecs = nowSeconds + BigInt(parseInt(deadlineHrs)) * 3600n;

      const txHash = await writer.writeContract({
        address: CONTRACT_ADDRESS,
        functionName: 'create_escrow',
        args: [sellerAddr.trim(), description, deadlineSecs],
        value: wei
      });

      setSuccessMessage(`Escrow transaction submitted: ${txHash}`);
      await waitForTx(writer, txHash);
      setSuccessMessage('Escrow created successfully!');
      
      setSellerAddr('');
      setAmountGen('');
      fetchTransactions();
    } catch (err) {
      setErrorMessage(err.message || 'Escrow creation failed');
    } finally {
      setLoading(false);
    }
  };

  const handleSellerSubmit = async () => {
    clearMessages();
    if (!account) return setErrorMessage('Connect your wallet first.');
    const cleaned = sellerUrls.map(u => u.trim()).filter(Boolean);
    if (cleaned.length === 0) return setErrorMessage('Add at least one proof URL.');
    if (!sellerStatement || sellerStatement.trim().length < 10) return setErrorMessage('Statement must be at least 10 chars.');

    setLoading(true);
    try {
      const writer = getWriteClient(account);
      const txHash = await writer.writeContract({
        address: CONTRACT_ADDRESS,
        functionName: 'submit_seller_evidence',
        args: [selectedTxId, cleaned, sellerStatement.trim()]
      });

      setSuccessMessage(`Evidence submitted: ${txHash}`);
      await waitForTx(writer, txHash);
      setSuccessMessage('Delivery proof submitted successfully!');
      setSellerUrls(['']);
      setSellerStatement('');
      fetchTxDetail(selectedTxId);
    } catch (err) {
      setErrorMessage(err.message || 'Evidence submission failed');
    } finally {
      setLoading(false);
    }
  };

  const handleBuyerSubmit = async () => {
    clearMessages();
    if (!account) return setErrorMessage('Connect your wallet first.');
    const cleaned = buyerUrls.map(u => u.trim()).filter(Boolean);
    if (!buyerStatement || buyerStatement.trim().length < 10) return setErrorMessage('Statement must be at least 10 chars.');

    setLoading(true);
    try {
      const writer = getWriteClient(account);
      const txHash = await writer.writeContract({
        address: CONTRACT_ADDRESS,
        functionName: 'submit_buyer_evidence',
        args: [selectedTxId, cleaned, buyerStatement.trim()]
      });

      setSuccessMessage(`Dispute filed: ${txHash}`);
      await waitForTx(writer, txHash);
      setSuccessMessage('Dispute counter-evidence submitted successfully!');
      setBuyerUrls(['']);
      setBuyerStatement('');
      fetchTxDetail(selectedTxId);
    } catch (err) {
      setErrorMessage(err.message || 'Buyer dispute submission failed');
    } finally {
      setLoading(false);
    }
  };

  const handleBuyerRelease = async () => {
    clearMessages();
    if (!account) return setErrorMessage('Connect your wallet first.');
    setLoading(true);
    try {
      const writer = getWriteClient(account);
      const txHash = await writer.writeContract({
        address: CONTRACT_ADDRESS,
        functionName: 'buyer_release_funds',
        args: [selectedTxId]
      });

      setSuccessMessage(`Cooperative release transaction submitted: ${txHash}`);
      await waitForTx(writer, txHash);
      setSuccessMessage('Escrow funds released to the seller cooperatively!');
      fetchTxDetail(selectedTxId);
    } catch (err) {
      setErrorMessage(err.message || 'Cooperative release failed');
    } finally {
      setLoading(false);
    }
  };

  const handleSellerRefund = async () => {
    clearMessages();
    if (!account) return setErrorMessage('Connect your wallet first.');
    setLoading(true);
    try {
      const writer = getWriteClient(account);
      const txHash = await writer.writeContract({
        address: CONTRACT_ADDRESS,
        functionName: 'seller_refund_buyer',
        args: [selectedTxId]
      });

      setSuccessMessage(`Cooperative refund transaction submitted: ${txHash}`);
      await waitForTx(writer, txHash);
      setSuccessMessage('Escrow funds refunded to the buyer cooperatively!');
      fetchTxDetail(selectedTxId);
    } catch (err) {
      setErrorMessage(err.message || 'Cooperative refund failed');
    } finally {
      setLoading(false);
    }
  };

  const handleResolveAI = async () => {
    clearMessages();
    if (!account) return setErrorMessage('Connect your wallet first.');
    setLoading(true);
    try {
      const writer = getWriteClient(account);
      const txHash = await writer.writeContract({
        address: CONTRACT_ADDRESS,
        functionName: 'resolve_escrow',
        args: [selectedTxId]
      });

      setSuccessMessage(`Adjudication requested: ${txHash}`);
      await waitForTx(writer, txHash);
      setSuccessMessage('AI Adjudication completed successfully!');
      fetchTxDetail(selectedTxId);
    } catch (err) {
      setErrorMessage(err.message || 'AI Adjudication failed');
    } finally {
      setLoading(false);
    }
  };

  const handleTimeoutRefund = async () => {
    clearMessages();
    if (!account) return setErrorMessage('Connect your wallet first.');
    setLoading(true);
    try {
      const writer = getWriteClient(account);
      const txHash = await writer.writeContract({
        address: CONTRACT_ADDRESS,
        functionName: 'claim_timeout_refund',
        args: [selectedTxId]
      });

      setSuccessMessage(`Timeout claim submitted: ${txHash}`);
      await waitForTx(writer, txHash);
      setSuccessMessage('Timeout refund executed successfully!');
      fetchTxDetail(selectedTxId);
    } catch (err) {
      setErrorMessage(err.message || 'Timeout refund failed');
    } finally {
      setLoading(false);
    }
  };

  const handleRetryFailedPayout = async () => {
    clearMessages();
    if (!account) return setErrorMessage('Connect your wallet first.');
    setLoading(true);
    try {
      const writer = getWriteClient(account);
      const txHash = await writer.writeContract({
        address: CONTRACT_ADDRESS,
        functionName: 'retry_resolution',
        args: [selectedTxId]
      });

      setSuccessMessage(`Retry transaction submitted: ${txHash}`);
      await waitForTx(writer, txHash);
      setSuccessMessage('Payout/Refund replayed successfully!');
      fetchTxDetail(selectedTxId);
    } catch (err) {
      setErrorMessage(err.message || 'Retry failed');
    } finally {
      setLoading(false);
    }
  };

  const addUrlField = (setter, state) => setter([...state, '']);
  const removeUrlField = (setter, state, idx) => setter(state.filter((_, i) => i !== idx));
  const updateUrlField = (setter, state, idx, val) => {
    const next = [...state];
    next[idx] = val;
    setter(next);
  };

  const formatDeadline = (ts) => {
    const date = new Date(parseInt(ts) * 1000);
    return date.toLocaleString();
  };

  const isExpired = (ts) => {
    return Date.now() / 1000 > parseInt(ts);
  };

  return (
    <div className="container">
      <header>
        <div>
          <h1>EquiSettle</h1>
          <p className="tagline">Symmetric Two-Party AI Escrow & Cooperative Settlement</p>
        </div>
        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          {account ? (
            <>
              <div className="wallet-badge connected">
                Connected: {account.slice(0, 6)}...{account.slice(-4)}
              </div>
              <button 
                className="btn-secondary" 
                onClick={() => setAccount('')} 
                style={{ padding: '0.4rem 0.8rem', fontSize: '0.8rem' }}
              >
                Disconnect
              </button>
            </>
          ) : (
            <button className="btn-primary" onClick={connectWallet}>
              Connect Wallet
            </button>
          )}
        </div>
      </header>

      {!hasContractAddress && (
        <div className="banner">
          <AlertTriangle color="#7b1d31" size={20} />
          <div>
            <span className="banner-title">Demo Mode:</span> No contract address configured in environment variable <code>VITE_CONTRACT_ADDRESS</code>. Read operations will fallback, writes are disabled.
          </div>
        </div>
      )}

      {errorMessage && (
        <div className="banner" style={{ background: '#fff2f2', borderColor: '#eea0a0' }}>
          <AlertTriangle color="#9c2a2a" size={20} />
          <div style={{ color: '#9c2a2a' }}>{errorMessage}</div>
        </div>
      )}

      {successMessage && (
        <div className="banner" style={{ background: '#f2fff6', borderColor: '#a0eea0' }}>
          <ThumbsUp color="#27523d" size={20} />
          <div style={{ color: '#27523d' }}>{successMessage}</div>
        </div>
      )}

      <div className="main-grid">
        {/* Left Column: Creator / List */}
        <div>
          <div className="card">
            <h2>New Secure Escrow</h2>
            <form onSubmit={handleCreateEscrow}>
              <div className="form-group">
                <label>Seller Address</label>
                <input 
                  type="text" 
                  placeholder="0x..." 
                  value={sellerAddr} 
                  onChange={e => setSellerAddr(e.target.value)}
                  disabled={loading}
                />
              </div>

              <div className="form-group">
                <label>Deal Category</label>
                <select 
                  value={category} 
                  onChange={e => setCategory(e.target.value)}
                  disabled={loading}
                >
                  {DEAL_CATEGORIES.map(c => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label>Escrow Terms & Description</label>
                <textarea 
                  rows={4} 
                  value={description} 
                  onChange={e => setDescription(e.target.value)}
                  disabled={loading}
                />
              </div>

              <div className="form-group" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                <div>
                  <label>Amount (GEN)</label>
                  <input 
                    type="number" 
                    step="0.0001" 
                    placeholder="e.g. 5.5" 
                    value={amountGen} 
                    onChange={e => setAmountGen(e.target.value)}
                    disabled={loading}
                  />
                </div>
                <div>
                  <label>Proof Deadline (Hours)</label>
                  <select 
                    value={deadlineHrs} 
                    onChange={e => setDeadlineHrs(e.target.value)}
                    disabled={loading}
                  >
                    <option value="1">1 Hour (Testing)</option>
                    <option value="12">12 Hours</option>
                    <option value="24">24 Hours</option>
                    <option value="72">3 Days</option>
                    <option value="168">7 Days</option>
                  </select>
                </div>
              </div>

              <button 
                type="submit" 
                className="btn-primary" 
                style={{ width: '100%', marginTop: '1rem' }}
                disabled={loading || !hasContractAddress}
              >
                <Lock size={16} /> Create Escrow & Lock Funds
              </button>
            </form>
          </div>

          <div className="card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.5rem' }}>
              <h2 style={{ borderBottom: 'none', marginBottom: 0, paddingBottom: 0 }}>My Escrow Trades</h2>
              <button 
                className="btn-secondary" 
                onClick={fetchTransactions} 
                style={{ padding: '0.35rem 0.75rem', fontSize: '0.75rem' }}
              >
                <RefreshCw size={12} /> Refresh
              </button>
            </div>

            <div className="form-group">
              <label>Filter by Status</label>
              <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
                <option value="">Show All Transactions</option>
                <option value="PENDING_DELIVERY">Pending Delivery</option>
                <option value="SUBMITTED">Submitted Proof</option>
                <option value="DISPUTED">Disputed / Filed Claims</option>
                <option value="RESOLVED">Resolved / Paid</option>
                <option value="REFUNDED">Refunded</option>
              </select>
            </div>

            <div className="tx-list">
              {transactions.length === 0 ? (
                <p style={{ textAlign: 'center', color: 'var(--text-secondary)', fontStyle: 'italic', padding: '1rem 0' }}>
                  No transactions found.
                </p>
              ) : (
                transactions.map(tx => (
                  <div 
                    key={tx.tx_id} 
                    className={`tx-item ${selectedTxId === tx.tx_id ? 'selected' : ''}`}
                    onClick={() => setSelectedTxId(tx.tx_id)}
                    style={{ cursor: 'pointer' }}
                  >
                    <div className="tx-header">
                      <span className="tx-id">#ID {tx.tx_id}</span>
                      <span className={`tx-status-badge status-${tx.status.toLowerCase()}`}>
                        {tx.status.replace('_', ' ')}
                      </span>
                    </div>
                    <p className="tx-body">
                      {tx.description.length > 80 ? `${tx.description.slice(0, 80)}...` : tx.description}
                    </p>
                    <div className="tx-footer">
                      <span>Value: <strong className="tx-amount">{formatWeiToGen(tx.amount)} GEN</strong></span>
                      <span>Expires: {formatDeadline(tx.deadline)}</span>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {/* Right Column: Detail & Adjudication */}
        <div>
          {selectedTx ? (
            <div className="detail-view">
              <h2>Adjudication & Escrow Details</h2>
              
              <div className="detail-row" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                <div>
                  <div className="detail-label">Escrow ID</div>
                  <div className="detail-value" style={{ fontFamily: 'var(--font-mono)' }}>#{selectedTx.tx_id}</div>
                </div>
                <div>
                  <div className="detail-label">Locked Value</div>
                  <div className="detail-value" style={{ fontWeight: 700, color: 'var(--accent-color)' }}>
                    {formatWeiToGen(selectedTx.amount)} GEN
                  </div>
                </div>
              </div>

              <div className="detail-row">
                <div className="detail-label">Buyer Account</div>
                <div className="detail-value" style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }}>{selectedTx.buyer}</div>
              </div>

              <div className="detail-row">
                <div className="detail-label">Seller Account</div>
                <div className="detail-value" style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }}>{selectedTx.seller}</div>
              </div>

              <div className="detail-row">
                <div className="detail-label">Contract Description</div>
                <div className="detail-value" style={{ whiteSpace: 'pre-wrap' }}>{selectedTx.description}</div>
              </div>

              <div className="detail-row" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                <div>
                  <div className="detail-label">Status State</div>
                  <span className={`tx-status-badge status-${selectedTx.status.toLowerCase()}`}>
                    {selectedTx.status.replace('_', ' ')}
                  </span>
                </div>
                <div>
                  <div className="detail-label">Submission Deadline</div>
                  <div className="detail-value" style={{ color: isExpired(selectedTx.deadline) ? 'var(--danger-color)' : 'var(--text-primary)' }}>
                    {formatDeadline(selectedTx.deadline)} {isExpired(selectedTx.deadline) && '(EXPIRED)'}
                  </div>
                </div>
              </div>

              {/* Cooperative Bypass Actions (Only for PENDING or DISPUTED) */}
              {!selectedTx.settled && (selectedTx.status === 'PENDING_DELIVERY' || selectedTx.status === 'DISPUTED' || selectedTx.status === 'SUBMITTED') && (
                <div className="detail-row">
                  <div className="detail-label">Cooperative Settlement (AI Bypass)</div>
                  <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '0.75rem' }}>
                    If you agree off-chain, settle immediately to save validator overhead.
                  </p>
                  <div className="btn-group">
                    {account.toLowerCase() === selectedTx.buyer.toLowerCase() && (
                      <button className="btn-secondary" onClick={handleBuyerRelease} disabled={loading}>
                        <Unlock size={14} /> Release locked funds to Seller
                      </button>
                    )}
                    {account.toLowerCase() === selectedTx.seller.toLowerCase() && (
                      <button className="btn-danger" onClick={handleSellerRefund} disabled={loading}>
                        <ArrowRight size={14} /> Refund locked funds to Buyer
                      </button>
                    )}
                  </div>
                </div>
              )}

              {/* Adjudication Verdict Result */}
              {selectedTx.verdict && (
                <div className="detail-row" style={{ background: '#f5f7f8', padding: '1rem', borderLeft: '4px solid var(--accent-color)' }}>
                  <div className="detail-label">AI Consensus Adjudication Verdict</div>
                  <div className="detail-value" style={{ fontWeight: 800, fontSize: '1.25rem', color: selectedTx.verdict === 'DELIVERED' ? 'var(--success-color)' : 'var(--danger-color)' }}>
                    {selectedTx.verdict}
                  </div>
                  <div style={{ fontSize: '0.85rem', margin: '0.5rem 0', fontStyle: 'italic' }}>
                    "{selectedTx.verdict_reason}"
                  </div>
                  <div className="tx-footer">
                    <span>Agreement Confidence: {selectedTx.confidence}%</span>
                  </div>
                </div>
              )}

              {/* Resolution Replays on Failed Native Payouts */}
              {(selectedTx.status === 'PAYOUT_FAILED' || selectedTx.status === 'REFUND_FAILED') && (
                <div className="detail-row" style={{ background: '#fff2f2', border: '1px dashed var(--danger-color)', padding: '1rem' }}>
                  <div className="detail-label" style={{ color: 'var(--danger-color)' }}>Transfer Failed</div>
                  <p style={{ fontSize: '0.8rem', marginBottom: '0.5rem' }}>
                    The native transfer did not complete successfully. Replay the payout using the existing verdict.
                  </p>
                  <button className="btn-primary" onClick={handleRetryFailedPayout} disabled={loading}>
                    <RefreshCw size={14} /> Replay Transfer
                  </button>
                </div>
              )}

              {/* Time expiration claim */}
              {!selectedTx.settled && isExpired(selectedTx.deadline) && (selectedTx.status === 'PENDING_DELIVERY' || selectedTx.status === 'DISPUTED') && (
                <div className="detail-row">
                  <div className="detail-label">Deadline Expired</div>
                  <p style={{ fontSize: '0.8rem', marginBottom: '0.5rem' }}>
                    The submission deadline has passed. The buyer can trigger a timeout refund.
                  </p>
                  {account.toLowerCase() === selectedTx.buyer.toLowerCase() && (
                    <button className="btn-danger" onClick={handleTimeoutRefund} disabled={loading}>
                      Claim Timeout Refund
                    </button>
                  )}
                </div>
              )}

              {/* Submissions Section */}
              <div className="detail-row">
                <div className="detail-label">Submissions</div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginTop: '0.5rem' }}>
                  <div>
                    <h4 style={{ fontSize: '0.8rem', fontWeight: 700 }}>Seller Proof</h4>
                    {selectedTx.seller_evidence.submitted ? (
                      <div className="evidence-block">
                        <p style={{ fontSize: '0.8rem', fontStyle: 'italic' }}>"{selectedTx.seller_evidence.statement}"</p>
                        <ul className="urls-list">
                          {selectedTx.seller_evidence.urls.map((u, i) => (
                            <li key={i}>
                              <a href={u} target="_blank" rel="noopener noreferrer">
                                <Link2 size={10} /> Link {i+1} <ExternalLink size={8} />
                              </a>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : (
                      <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontStyle: 'italic' }}>No proof submitted yet.</span>
                    )}
                  </div>
                  <div>
                    <h4 style={{ fontSize: '0.8rem', fontWeight: 700 }}>Buyer Dispute</h4>
                    {selectedTx.buyer_evidence.submitted ? (
                      <div className="evidence-block" style={{ borderLeftColor: 'var(--danger-color)' }}>
                        <p style={{ fontSize: '0.8rem', fontStyle: 'italic' }}>"{selectedTx.buyer_evidence.statement}"</p>
                        <ul className="urls-list">
                          {selectedTx.buyer_evidence.urls.map((u, i) => (
                            <li key={i}>
                              <a href={u} target="_blank" rel="noopener noreferrer">
                                <Link2 size={10} /> Link {i+1} <ExternalLink size={8} />
                              </a>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : (
                      <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontStyle: 'italic' }}>No dispute counter-evidence.</span>
                    )}
                  </div>
                </div>
              </div>

              {/* SELLER ACTION: Submit proof */}
              {!selectedTx.settled && account.toLowerCase() === selectedTx.seller.toLowerCase() && !isExpired(selectedTx.deadline) && (
                <div className="detail-row" style={{ background: '#fdfdfd', border: '1px solid var(--border-color)', padding: '1.25rem' }}>
                  <h3 style={{ fontFamily: 'var(--font-serif)', fontSize: '1.1rem', marginBottom: '0.75rem' }}>Seller: Upload Delivery Proof</h3>
                  <div className="form-group">
                    <label>Proof URL(s)</label>
                    {sellerUrls.map((u, idx) => (
                      <div key={idx} className="url-input-row">
                        <input 
                          type="text" 
                          placeholder="https://..." 
                          value={u}
                          onChange={e => updateUrlField(setSellerUrls, sellerUrls, idx, e.target.value)}
                        />
                        {sellerUrls.length > 1 && (
                          <button type="button" className="btn-secondary" style={{ padding: '0.5rem' }} onClick={() => removeUrlField(setSellerUrls, sellerUrls, idx)}>
                            <Trash size={12} />
                          </button>
                        )}
                      </div>
                    ))}
                    <button type="button" className="btn-secondary" style={{ padding: '0.35rem 0.75rem', fontSize: '0.75rem', marginTop: '0.25rem' }} onClick={() => addUrlField(setSellerUrls, sellerUrls)}>
                      + Add URL
                    </button>
                  </div>
                  <div className="form-group">
                    <label>Delivery Statement</label>
                    <textarea 
                      rows={2} 
                      placeholder="Detail shipment code, tracking status, or file hash."
                      value={sellerStatement}
                      onChange={e => setSellerStatement(e.target.value)}
                    />
                  </div>
                  <button className="btn-primary" style={{ width: '100%' }} onClick={handleSellerSubmit} disabled={loading}>
                    Lock Delivery Evidence
                  </button>
                </div>
              )}

              {/* BUYER ACTION: File dispute */}
              {!selectedTx.settled && account.toLowerCase() === selectedTx.buyer.toLowerCase() && (
                <div className="detail-row" style={{ background: '#fdfdfd', border: '1px solid var(--border-color)', padding: '1.25rem' }}>
                  <h3 style={{ fontFamily: 'var(--font-serif)', fontSize: '1.1rem', marginBottom: '0.75rem', color: 'var(--danger-color)' }}>Buyer: File Dispute & Counter-Evidence</h3>
                  <div className="form-group">
                    <label>Dispute Proof URL(s) (Optional)</label>
                    {buyerUrls.map((u, idx) => (
                      <div key={idx} className="url-input-row">
                        <input 
                          type="text" 
                          placeholder="https://..." 
                          value={u}
                          onChange={e => updateUrlField(setBuyerUrls, buyerUrls, idx, e.target.value)}
                        />
                        {buyerUrls.length > 1 && (
                          <button type="button" className="btn-secondary" style={{ padding: '0.5rem' }} onClick={() => removeUrlField(setBuyerUrls, buyerUrls, idx)}>
                            <Trash size={12} />
                          </button>
                        )}
                      </div>
                    ))}
                    <button type="button" className="btn-secondary" style={{ padding: '0.35rem 0.75rem', fontSize: '0.75rem', marginTop: '0.25rem' }} onClick={() => addUrlField(setBuyerUrls, buyerUrls)}>
                      + Add URL
                    </button>
                  </div>
                  <div className="form-group">
                    <label>Dispute Statement</label>
                    <textarea 
                      rows={2} 
                      placeholder="Explain what is missing, damaged, or incorrect."
                      value={buyerStatement}
                      onChange={e => setBuyerStatement(e.target.value)}
                    />
                  </div>
                  <button className="btn-danger" style={{ width: '100%' }} onClick={handleBuyerSubmit} disabled={loading}>
                    Lock Dispute Evidence & Flag Escrow
                  </button>
                </div>
              )}

              {/* AI adjudication resolve trigger */}
              {!selectedTx.settled && (selectedTx.status === 'SUBMITTED' || selectedTx.status === 'DISPUTED') && (
                <div className="detail-row" style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', borderBottom: 'none' }}>
                  <button className="btn-primary" style={{ width: '100%', padding: '1rem', background: '#2c2c2a', borderColor: '#2c2c2a' }} onClick={handleResolveAI} disabled={loading}>
                    <Scale size={18} /> Request AI Adjudication Verdict
                  </button>
                  {loading && (
                    <div style={{ textAlign: 'center', fontSize: '0.8rem', fontStyle: 'italic', color: 'var(--text-secondary)' }}>
                      Connecting to GenLayer validators for non-deterministic AI consensus<span className="loading-dots"><span>.</span><span>.</span><span>.</span></span>
                    </div>
                  )}
                </div>
              )}

            </div>
          ) : (
            <div className="detail-view" style={{ textAlign: 'center', padding: '5rem 2rem', background: 'var(--panel-bg)', color: 'var(--text-secondary)' }}>
              <Shield size={48} color="var(--border-color)" style={{ margin: '0 auto 1.5rem' }} />
              <p style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: '1.2rem' }}>
                Select an active transaction from your trade list to view adjudication status, submit evidence, or cooperative release.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
