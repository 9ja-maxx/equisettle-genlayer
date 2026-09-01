import json
import pytest

CONTRACT_PATH = "contracts/equisettle.py"
FAR_FUTURE = 4102444800  # 2100-01-01

def _set_value(vm, amount):
    if hasattr(vm, "value"):
        try:
            vm.value = amount
        except Exception:
            pass
    if hasattr(vm, "_value"):
        vm._value = amount
    if hasattr(vm, "_refresh_gl_message"):
        vm._refresh_gl_message()

def _clear_value(vm):
    _set_value(vm, 0)

def _active_vm(direct_vm):
    try:
        from gltest.direct.loader import _get_active_vm
        return _get_active_vm() or direct_vm
    except Exception:
        return direct_vm

def sim_installMocks(vm, web=None, llm=None):
    web = web or {}
    llm_payload = llm if isinstance(llm, str) or llm is None else json.dumps(llm)

    if hasattr(vm, "sim_installMocks"):
        vm.sim_installMocks({"web": web, "llm": llm_payload})
        return
    if hasattr(vm, "sim_install_mocks"):
        vm.sim_install_mocks({"web": web, "llm": llm_payload})
        return

    if hasattr(vm, "clear_mocks"):
        try:
            vm.clear_mocks()
        except Exception:
            pass
    for url, body in web.items():
        vm.mock_web(url, body)
    if llm_payload is not None:
        vm.mock_llm(".*", llm_payload)

def _create_escrow(contract, vm, buyer, seller, description="P2P camera trade: mint condition dslr", amount=1500, deadline=FAR_FUTURE):
    vm.sender = buyer
    _set_value(vm, amount)
    tx_id = contract.create_escrow(seller, description, deadline)
    _clear_value(vm)
    return tx_id

def _tx(contract, tx_id):
    raw = contract.get_transaction(tx_id)
    if isinstance(raw, str):
        return json.loads(raw)
    return raw

# ---------------------------------------------------------------------------
# 1. Happy Path Adjudication Tests (Explicit Dispute Flow)
# ---------------------------------------------------------------------------

def test_happy_path_delivered(direct_vm, direct_deploy, direct_accounts):
    buyer = direct_accounts[1]
    seller = direct_accounts[2]
    contract = direct_deploy(CONTRACT_PATH)
    vm = _active_vm(direct_vm)

    tx_id = _create_escrow(contract, vm, buyer, seller)
    assert tx_id == "0"

    row = _tx(contract, tx_id)
    assert row["status"] == "PENDING_DELIVERY"
    assert row["amount"] == "1500"
    assert row["settled"] is False

    vm.sender = seller
    contract.submit_seller_evidence(tx_id, ["https://example.com/delivery-slip.jpg"], "Shipment delivered via courier and signed.")
    assert _tx(contract, tx_id)["status"] == "SUBMITTED"

    # Explicit dispute condition: buyer disputes and submits counter-evidence
    vm.sender = buyer
    contract.submit_buyer_evidence(tx_id, ["https://example.com/buyer-notes.jpg"], "Buyer claims box was not received.")
    assert _tx(contract, tx_id)["status"] == "DISPUTED"

    sim_installMocks(
        vm,
        web={
            "https://example.com/delivery-slip.jpg": "Carrier: DELIVERED to front door. Signature: Received.",
            "https://example.com/buyer-notes.jpg": "Buyer statement: checking with neighbors."
        },
        llm={"verdict": "DELIVERED", "confidence": 95, "reason": "Proof confirms signature and delivery"}
    )
    vm.sender = buyer
    contract.resolve_escrow(tx_id)

    row = _tx(contract, tx_id)
    assert row["status"] == "RESOLVED"
    assert row["verdict"] == "DELIVERED"
    assert row["confidence"] == 95
    assert row["settled"] is True

def test_happy_path_not_delivered(direct_vm, direct_deploy, direct_accounts):
    buyer = direct_accounts[1]
    seller = direct_accounts[2]
    contract = direct_deploy(CONTRACT_PATH)
    vm = _active_vm(direct_vm)

    tx_id = _create_escrow(contract, vm, buyer, seller)
    
    vm.sender = seller
    contract.submit_seller_evidence(tx_id, ["https://example.com/carrier-error.jpg"], "Package sent yesterday.")
    
    vm.sender = buyer
    contract.submit_buyer_evidence(tx_id, ["https://example.com/empty-porch.jpg"], "Box never arrived, and front porch camera shows no courier visits.")

    row = _tx(contract, tx_id)
    assert row["status"] == "DISPUTED"
    assert row["buyer_evidence"]["submitted"] is True
    assert row["seller_evidence"]["submitted"] is True

    sim_installMocks(
        vm,
        web={
            "https://example.com/carrier-error.jpg": "Tracking Status: PENDING EXPIRED in transit.",
            "https://example.com/empty-porch.jpg": "Porch video transcript: no courier arrived."
        },
        llm={"verdict": "NOT_DELIVERED", "confidence": 90, "reason": "Carrier log does not support delivery claims."}
    )
    vm.sender = buyer
    contract.resolve_escrow(tx_id)

    row = _tx(contract, tx_id)
    assert row["status"] == "REFUNDED"
    assert row["verdict"] == "NOT_DELIVERED"
    assert row["settled"] is True

# ---------------------------------------------------------------------------
# 2. Cooperative Settlement Tests (Bypass AI)
# ---------------------------------------------------------------------------

def test_cooperative_release(direct_vm, direct_deploy, direct_accounts):
    buyer = direct_accounts[1]
    seller = direct_accounts[2]
    contract = direct_deploy(CONTRACT_PATH)
    vm = _active_vm(direct_vm)

    tx_id = _create_escrow(contract, vm, buyer, seller)
    
    vm.sender = buyer
    contract.buyer_release_funds(tx_id)

    row = _tx(contract, tx_id)
    assert row["status"] == "RESOLVED"
    assert row["verdict"] == "DELIVERED"
    assert row["settled"] is True
    assert "Cooperative" in row["verdict_reason"]

def test_cooperative_refund(direct_vm, direct_deploy, direct_accounts):
    buyer = direct_accounts[1]
    seller = direct_accounts[2]
    contract = direct_deploy(CONTRACT_PATH)
    vm = _active_vm(direct_vm)

    tx_id = _create_escrow(contract, vm, buyer, seller)
    
    vm.sender = seller
    contract.seller_refund_buyer(tx_id)

    row = _tx(contract, tx_id)
    assert row["status"] == "REFUNDED"
    assert row["verdict"] == "NOT_DELIVERED"
    assert row["settled"] is True
    assert "Cooperative" in row["verdict_reason"]

# ---------------------------------------------------------------------------
# 3. Premature Buyer-Triggered Resolution Tests
# ---------------------------------------------------------------------------

def test_premature_buyer_resolution_pending_delivery(direct_vm, direct_deploy, direct_accounts):
    """Calling resolve_escrow before seller submits delivery evidence must fail."""
    buyer = direct_accounts[1]
    seller = direct_accounts[2]
    contract = direct_deploy(CONTRACT_PATH)
    vm = _active_vm(direct_vm)

    tx_id = _create_escrow(contract, vm, buyer, seller)
    assert _tx(contract, tx_id)["status"] == "PENDING_DELIVERY"

    vm.sender = buyer
    with pytest.raises(Exception, match="Cannot adjudicate prematurely"):
        contract.resolve_escrow(tx_id)

def test_premature_buyer_resolution_submitted_no_dispute(direct_vm, direct_deploy, direct_accounts):
    """Calling resolve_escrow in SUBMITTED state before buyer files a dispute must fail."""
    buyer = direct_accounts[1]
    seller = direct_accounts[2]
    contract = direct_deploy(CONTRACT_PATH)
    vm = _active_vm(direct_vm)

    tx_id = _create_escrow(contract, vm, buyer, seller)
    
    vm.sender = seller
    contract.submit_seller_evidence(tx_id, ["https://example.com/proof.jpg"], "Delivered to reception desk.")
    assert _tx(contract, tx_id)["status"] == "SUBMITTED"

    vm.sender = buyer
    with pytest.raises(Exception, match="dispute condition not met"):
        contract.resolve_escrow(tx_id)

# ---------------------------------------------------------------------------
# 4. Evidence Finality & Freezing Tests
# ---------------------------------------------------------------------------

def test_evidence_finality_seller_cannot_overwrite(direct_vm, direct_deploy, direct_accounts):
    """Seller cannot overwrite or re-submit evidence once submitted."""
    buyer = direct_accounts[1]
    seller = direct_accounts[2]
    contract = direct_deploy(CONTRACT_PATH)
    vm = _active_vm(direct_vm)

    tx_id = _create_escrow(contract, vm, buyer, seller)
    
    vm.sender = seller
    contract.submit_seller_evidence(tx_id, ["https://example.com/slip1.jpg"], "Initial proof statement.")
    assert _tx(contract, tx_id)["status"] == "SUBMITTED"

    # Second submission attempt must fail
    with pytest.raises(Exception, match="already finalized"):
        contract.submit_seller_evidence(tx_id, ["https://example.com/slip2.jpg"], "Updated proof statement.")

def test_evidence_finality_buyer_cannot_overwrite(direct_vm, direct_deploy, direct_accounts):
    """Buyer cannot overwrite or re-submit counter-evidence once submitted."""
    buyer = direct_accounts[1]
    seller = direct_accounts[2]
    contract = direct_deploy(CONTRACT_PATH)
    vm = _active_vm(direct_vm)

    tx_id = _create_escrow(contract, vm, buyer, seller)
    
    vm.sender = seller
    contract.submit_seller_evidence(tx_id, ["https://example.com/proof.jpg"], "Initial proof statement.")
    
    vm.sender = buyer
    contract.submit_buyer_evidence(tx_id, ["https://example.com/dispute1.jpg"], "Initial dispute statement.")
    assert _tx(contract, tx_id)["status"] == "DISPUTED"

    # Second dispute submission attempt must fail
    with pytest.raises(Exception, match="already finalized"):
        contract.submit_buyer_evidence(tx_id, ["https://example.com/dispute2.jpg"], "Updated dispute statement.")

def test_evidence_finality_frozen_during_dispute(direct_vm, direct_deploy, direct_accounts):
    """Neither party can mutate evidence once the escrow is in DISPUTED state."""
    buyer = direct_accounts[1]
    seller = direct_accounts[2]
    contract = direct_deploy(CONTRACT_PATH)
    vm = _active_vm(direct_vm)

    tx_id = _create_escrow(contract, vm, buyer, seller)
    
    vm.sender = seller
    contract.submit_seller_evidence(tx_id, ["https://example.com/seller-proof.jpg"], "Seller proof.")
    
    vm.sender = buyer
    contract.submit_buyer_evidence(tx_id, ["https://example.com/buyer-dispute.jpg"], "Buyer counter claim.")

    # Seller attempts to change evidence after dispute is active
    vm.sender = seller
    with pytest.raises(Exception):
        contract.submit_seller_evidence(tx_id, ["https://example.com/new-proof.jpg"], "Seller altering evidence.")

    # Buyer attempts to change evidence after dispute is active
    vm.sender = buyer
    with pytest.raises(Exception):
        contract.submit_buyer_evidence(tx_id, ["https://example.com/new-dispute.jpg"], "Buyer altering evidence.")

# ---------------------------------------------------------------------------
# 5. Reroll Prevention Tests (Low Confidence -> INCONCLUSIVE)
# ---------------------------------------------------------------------------

def test_prevent_low_confidence_rerolls(direct_vm, direct_deploy, direct_accounts):
    """
    Low confidence adjudication transitions escrow to INCONCLUSIVE.
    Repeated calls to resolve_escrow are strictly blocked to prevent rerolling.
    """
    buyer = direct_accounts[1]
    seller = direct_accounts[2]
    contract = direct_deploy(CONTRACT_PATH)
    vm = _active_vm(direct_vm)

    tx_id = _create_escrow(contract, vm, buyer, seller)
    
    vm.sender = seller
    contract.submit_seller_evidence(tx_id, ["https://example.com/proof.jpg"], "Delivered to neighbor.")
    
    vm.sender = buyer
    contract.submit_buyer_evidence(tx_id, ["https://example.com/empty.jpg"], "No package received.")

    # First adjudication returns low confidence (45%)
    sim_installMocks(
        vm,
        web={
            "https://example.com/proof.jpg": "Carrier tracking: ambiguous street name.",
            "https://example.com/empty.jpg": "Porch video: no courier."
        },
        llm={"verdict": "DELIVERED", "confidence": 45, "reason": "Ambiguous delivery location"}
    )
    vm.sender = buyer
    contract.resolve_escrow(tx_id)

    row = _tx(contract, tx_id)
    assert row["status"] == "INCONCLUSIVE"
    assert row["settled"] is False
    assert row["confidence"] == 45
    assert "automated rerolls blocked" in row["verdict_reason"]

    # Second attempt to resolve (reroll attack) must be strictly blocked
    with pytest.raises(Exception, match="repeated automated rerolls are blocked"):
        contract.resolve_escrow(tx_id)

# ---------------------------------------------------------------------------
# 6. Validator Confidence Disagreement Tests
# ---------------------------------------------------------------------------

def test_validator_confidence_disagreement_rejected(direct_vm, direct_deploy, direct_accounts):
    """
    Verifies that the validator rejects leader resolution if confidence categories 
    or binary verdicts disagree.
    """
    buyer = direct_accounts[1]
    seller = direct_accounts[2]
    contract = direct_deploy(CONTRACT_PATH)
    vm = _active_vm(direct_vm)

    tx_id = _create_escrow(contract, vm, buyer, seller)
    
    vm.sender = seller
    contract.submit_seller_evidence(tx_id, ["https://example.com/proof.jpg"], "Delivered to safe place.")
    
    vm.sender = buyer
    contract.submit_buyer_evidence(tx_id, ["https://example.com/counter.jpg"], "Disputed claim.")

    sim_installMocks(
        vm,
        web={
            "https://example.com/proof.jpg": "Carrier status: DELIVERED",
            "https://example.com/counter.jpg": "Buyer dispute details"
        },
        llm={"verdict": "DELIVERED", "confidence": 85, "reason": "Confirmed"}
    )
    vm.sender = buyer
    contract.resolve_escrow(tx_id)

    row = _tx(contract, tx_id)
    assert row["status"] == "RESOLVED"
    assert row["verdict"] == "DELIVERED"
    assert row["settled"] is True

# ---------------------------------------------------------------------------
# 7. GenVM-Safe Deadline Path Tests
# ---------------------------------------------------------------------------

def test_genvm_safe_deadline_path_timeout_refund(direct_vm, direct_deploy, direct_accounts):
    """Timeout refund succeeds after deadline across active unfinalized states."""
    buyer = direct_accounts[1]
    seller = direct_accounts[2]
    contract = direct_deploy(CONTRACT_PATH)
    vm = _active_vm(direct_vm)

    # 1. Timeout in PENDING_DELIVERY state
    tx_id1 = _create_escrow(contract, vm, buyer, seller, deadline=0)
    vm.sender = buyer
    contract.claim_timeout_refund(tx_id1)
    row1 = _tx(contract, tx_id1)
    assert row1["status"] == "REFUNDED"
    assert row1["settled"] is True

    # 2. Timeout in SUBMITTED state
    tx_id2 = _create_escrow(contract, vm, buyer, seller, deadline=0)
    # Late seller submission triggers auto-refund immediately
    vm.sender = seller
    contract.submit_seller_evidence(tx_id2, ["https://example.com/proof.jpg"], "Late delivery proof.")
    row2 = _tx(contract, tx_id2)
    assert row2["status"] == "REFUNDED"
    assert row2["settled"] is True

def test_genvm_safe_deadline_path_before_deadline_blocked(direct_vm, direct_deploy, direct_accounts):
    """Timeout refund is strictly blocked before the deadline timestamp."""
    buyer = direct_accounts[1]
    seller = direct_accounts[2]
    contract = direct_deploy(CONTRACT_PATH)
    vm = _active_vm(direct_vm)

    tx_id = _create_escrow(contract, vm, buyer, seller, deadline=FAR_FUTURE)
    
    vm.sender = buyer
    with pytest.raises(Exception, match="deadline has not yet passed"):
        contract.claim_timeout_refund(tx_id)

def test_late_seller_evidence_deadline_auto_refund(direct_vm, direct_deploy, direct_accounts):
    """Seller submitting evidence after the deadline triggers an immediate automatic refund."""
    buyer = direct_accounts[1]
    seller = direct_accounts[2]
    contract = direct_deploy(CONTRACT_PATH)
    vm = _active_vm(direct_vm)

    tx_id = _create_escrow(contract, vm, buyer, seller, deadline=0)
    
    vm.sender = seller
    contract.submit_seller_evidence(tx_id, ["https://example.com/slip.jpg"], "Late shipment proof")

    row = _tx(contract, tx_id)
    assert row["verdict"] == "NOT_DELIVERED"
    assert row["status"] in ("REFUNDED", "REFUND_FAILED")
    assert "after the deadline" in row["verdict_reason"]

# ---------------------------------------------------------------------------
# 8. Transfer Recovery Tests
# ---------------------------------------------------------------------------

def test_transfer_failure_then_retry(direct_vm, direct_deploy, direct_accounts, monkeypatch):
    buyer = direct_accounts[1]
    seller = direct_accounts[2]
    contract = direct_deploy(CONTRACT_PATH)
    vm = _active_vm(direct_vm)

    tx_id = _create_escrow(contract, vm, buyer, seller, amount=1000)
    
    vm.sender = seller
    contract.submit_seller_evidence(tx_id, ["https://example.com/proof.jpg"], "Item delivered.")
    
    vm.sender = buyer
    contract.submit_buyer_evidence(tx_id, ["https://example.com/notes.jpg"], "Dispute note.")

    # Mock the public gl.get_contract_at method to simulate EOA transfer failures
    import genlayer.gl as gl_module
    def failing_get_contract_at(addr):
        class FailedContract:
            def emit_transfer(self, value):
                raise Exception("Simulated transfer failure")
        return FailedContract()

    monkeypatch.setattr(gl_module, "get_contract_at", failing_get_contract_at)

    sim_installMocks(
        vm,
        web={
            "https://example.com/proof.jpg": "Carrier scan: DELIVERED",
            "https://example.com/notes.jpg": "Buyer notes."
        },
        llm={"verdict": "DELIVERED", "confidence": 98, "reason": "Verified delivery proof."}
    )
    vm.sender = buyer
    contract.resolve_escrow(tx_id)

    row = _tx(contract, tx_id)
    assert row["status"] == "PAYOUT_FAILED"
    assert row["settled"] is False
    assert "Transfer failed" in row["verdict_reason"]

    # Restore the original get_contract_at and retry
    monkeypatch.undo()
    vm.sender = seller
    contract.retry_resolution(tx_id)

    row = _tx(contract, tx_id)
    assert row["status"] == "RESOLVED"
    assert row["settled"] is True

