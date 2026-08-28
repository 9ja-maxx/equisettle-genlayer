# v0.2.16
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *

import json
from dataclasses import dataclass

def _addr_str(a: Address) -> str:
    """Helper to convert Address type safely into a hexadecimal string."""
    try:
        return a.as_hex
    except Exception:
        return str(a)

def _to_address(val) -> Address:
    """Safely cast incoming values (like hex strings or raw types) into a clean GenLayer Address."""
    if isinstance(val, Address):
        return val
    if isinstance(val, str):
        val_str = val.strip()
        if not val_str.startswith("0x"):
            val_str = "0x" + val_str
        return Address(val_str)
    return Address(val)

def _now_ts() -> u256:
    """
    Get current Unix time in seconds.
    Note: Under GenVM validator execution, this call is caught by VM interception 
    or mocked during deterministic test suites to prevent node validation splits.
    """
    import time
    return u256(int(time.time()))

def _extract_result(result) -> dict:
    """Safely extracts JSON payload dictionaries from non-deterministic execution returns."""
    if isinstance(result, dict):
        return result
    if hasattr(result, "calldata") and isinstance(result.calldata, dict):
        return result.calldata
    if hasattr(result, "value") and isinstance(result.value, dict):
        return result.value
    raise gl.vm.UserError("Failed to extract valid non-deterministic consensus result structure")

def _safe_transfer(recipient: Address, amount: bigint) -> bool:
    """
    Emits an on-chain transfer to the EOA or contract address proxy.
    By capturing errors, it prevents execution crashes from freezing escrow status.
    """
    if amount <= bigint(0):
        return True
    try:
        gl.get_contract_at(_to_address(recipient)).emit_transfer(value=u256(amount))
        return True
    except Exception:
        return False

@allow_storage
@dataclass
class EvidenceSubmission:
    """
    Represents a submission of proof/dispute files and arguments by either party.
    This architecture supports symmetric, two-sided evidence collection.
    """
    submitted: bool
    urls: DynArray[str]
    statement: str
    timestamp: u256

@allow_storage
@dataclass
class EscrowTransaction:
    """
    State record containing all parameters, rules, and outcomes for a single escrow.
    """
    buyer: Address
    seller: Address
    description: str
    amount: bigint
    deadline: u256
    buyer_evidence: EvidenceSubmission
    seller_evidence: EvidenceSubmission
    status: str      # PENDING_DELIVERY, SUBMITTED, DISPUTED, RESOLVED, REFUNDED, PAYOUT_FAILED, REFUND_FAILED
    verdict: str     # DELIVERED, NOT_DELIVERED
    verdict_reason: str
    confidence: bigint
    settled: bool

class EquiSettle(gl.Contract):
    """
    EquiSettle: A professional, cooperative, and symmetric AI-adjudicated escrow protocol.
    Directly addresses key limitations of standard single-party escrows:
    1. Supports cooperative early bypass (buyer releases or seller refunds directly).
    2. Allows symmetric buyer and seller evidence submissions.
    3. Prevents consensus aborts due to minor subjective confidence score variations.
    """
    owner: Address
    tx_counter: bigint
    transactions: TreeMap[str, EscrowTransaction]

    def __init__(self):
        self.owner = _to_address(gl.message.sender_address)
        self.tx_counter = bigint(0)

    def _settle(self, tx: EscrowTransaction, verdict: str, reason: str, confidence: int) -> EscrowTransaction:
        """Helper to distribute funds to the appropriate party based on the verdict."""
        tx.verdict = verdict
        tx.confidence = bigint(confidence)
        tx.verdict_reason = reason
        
        recipient = tx.seller if verdict == "DELIVERED" else tx.buyer
        ok = _safe_transfer(recipient, tx.amount)
        
        if ok:
            tx.settled = True
            tx.status = "RESOLVED" if verdict == "DELIVERED" else "REFUNDED"
        else:
            tx.settled = False
            tx.status = "PAYOUT_FAILED" if verdict == "DELIVERED" else "REFUND_FAILED"
            tx.verdict_reason += " (Transfer failed, retryable)"
        return tx

    @gl.public.write.payable
    def create_escrow(self, seller: Address, description: str, deadline: u256) -> str:
        """
        Buyers call this to open an escrow and lock native GEN.
        Input validation blocks self-deals, zero-value escrows, and empty terms.
        """
        amount = bigint(gl.message.value)
        if amount <= bigint(0):
            raise gl.vm.UserError("Must lock a positive amount of GEN (> 0)")
        if not description or len(description.strip()) == 0 or len(description) > 3000:
            raise gl.vm.UserError("Description must be between 1 and 3000 characters")

        buyer = _to_address(gl.message.sender_address)
        seller_addr = _to_address(seller)
        if buyer == seller_addr:
            raise gl.vm.UserError("Buyer and seller cannot be the same account")

        tx_id = str(self.tx_counter)
        self.tx_counter += bigint(1)

        empty_urls = []
        no_evidence = EvidenceSubmission(
            submitted=False,
            urls=empty_urls,
            statement="",
            timestamp=u256(0)
        )

        self.transactions[tx_id] = EscrowTransaction(
            buyer=buyer,
            seller=seller_addr,
            description=description.strip(),
            amount=amount,
            deadline=deadline,
            buyer_evidence=no_evidence,
            seller_evidence=no_evidence,
            status="PENDING_DELIVERY",
            verdict="",
            verdict_reason="",
            confidence=bigint(0),
            settled=False
        )
        return tx_id

    @gl.public.write
    def submit_seller_evidence(self, tx_id: str, urls: DynArray[str], statement: str) -> None:
        """
        Sellers call this to submit proof of delivery (e.g. shipment tracking, files, portals).
        Requires at least 1 proof link and a detailed descriptive statement.
        """
        if tx_id not in self.transactions:
            raise gl.vm.UserError("Escrow transaction not found")

        tx = self.transactions[tx_id]
        if tx.settled:
            raise gl.vm.UserError("Escrow already settled")
        if tx.status not in ["PENDING_DELIVERY", "DISPUTED", "SUBMITTED"]:
            raise gl.vm.UserError(f"Cannot submit proof in state: {tx.status}")

        sender = _to_address(gl.message.sender_address)
        if sender != tx.seller:
            raise gl.vm.UserError("Only the seller can submit delivery evidence")

        if len(urls) < 1:
            raise gl.vm.UserError("At least 1 proof URL is required")
        if not statement or len(statement.strip()) < 10:
            raise gl.vm.UserError("Seller statement must be at least 10 characters long")

        cleaned_urls = []
        for u in urls:
            url = str(u).strip()
            if not url or not (url.startswith("http://") or url.startswith("https://")):
                raise gl.vm.UserError("Invalid evidence URL; must start with http:// or https://")
            cleaned_urls.append(url)

        # Record seller evidence submission
        tx.seller_evidence = EvidenceSubmission(
            submitted=True,
            urls=cleaned_urls,
            statement=statement.strip(),
            timestamp=_now_ts()
        )

        # Auto-refund if submitted after deadline (bypasses LLM consensus to enforce deadline rules)
        if _now_ts() > tx.deadline:
            tx = self._settle(
                tx,
                "NOT_DELIVERED",
                "Evidence submitted after the deadline; automatic refund to buyer.",
                100
            )
            self.transactions[tx_id] = tx
            return

        tx.status = "SUBMITTED"
        self.transactions[tx_id] = tx

    @gl.public.write
    def submit_buyer_evidence(self, tx_id: str, urls: DynArray[str], statement: str) -> None:
        """
        Buyers call this to dispute a delivery or present counter-evidence of fraud/non-delivery.
        Ensures a symmetric, two-sided review before the AI judges the dispute.
        """
        if tx_id not in self.transactions:
            raise gl.vm.UserError("Escrow transaction not found")

        tx = self.transactions[tx_id]
        if tx.settled:
            raise gl.vm.UserError("Escrow already settled")
        
        sender = _to_address(gl.message.sender_address)
        if sender != tx.buyer:
            raise gl.vm.UserError("Only the buyer can submit counter-evidence")

        if not statement or len(statement.strip()) < 10:
            raise gl.vm.UserError("Buyer statement must be at least 10 characters long")

        cleaned_urls = []
        for u in urls:
            url = str(u).strip()
            if not url or not (url.startswith("http://") or url.startswith("https://")):
                raise gl.vm.UserError("Invalid evidence URL; must start with http:// or https://")
            cleaned_urls.append(url)

        # Record buyer evidence submission
        tx.buyer_evidence = EvidenceSubmission(
            submitted=True,
            urls=cleaned_urls,
            statement=statement.strip(),
            timestamp=_now_ts()
        )

        # Once a buyer submits counter-evidence, the escrow is flagged as disputed
        tx.status = "DISPUTED"
        self.transactions[tx_id] = tx

    @gl.public.write
    def buyer_release_funds(self, tx_id: str) -> None:
        """
        Cooperative release: Buyer releases funds to the seller early.
        Bypasses AI consensus entirely to support cooperative settlements.
        """
        if tx_id not in self.transactions:
            raise gl.vm.UserError("Escrow transaction not found")

        tx = self.transactions[tx_id]
        if tx.settled:
            raise gl.vm.UserError("Escrow already settled")

        sender = _to_address(gl.message.sender_address)
        if sender != tx.buyer:
            raise gl.vm.UserError("Only the buyer can cooperatively release funds")

        tx = self._settle(
            tx,
            "DELIVERED",
            "Cooperative settlement: buyer released locked funds to the seller.",
            100
        )
        self.transactions[tx_id] = tx

    @gl.public.write
    def seller_refund_buyer(self, tx_id: str) -> None:
        """
        Cooperative refund: Seller returns locked funds to the buyer early.
        Bypasses AI consensus entirely to support cooperative cancellations.
        """
        if tx_id not in self.transactions:
            raise gl.vm.UserError("Escrow transaction not found")

        tx = self.transactions[tx_id]
        if tx.settled:
            raise gl.vm.UserError("Escrow already settled")

        sender = _to_address(gl.message.sender_address)
        if sender != tx.seller:
            raise gl.vm.UserError("Only the seller can cooperatively refund the buyer")

        tx = self._settle(
            tx,
            "NOT_DELIVERED",
            "Cooperative settlement: seller refunded locked funds to the buyer.",
            100
        )
        self.transactions[tx_id] = tx

    @gl.public.write
    def resolve_escrow(self, tx_id: str) -> None:
        """
        Executes decentralized AI adjudication using validator consensus.
        Gathers evidence from BOTH sides and parses it symmetrically.
        Hardens consensus by checking ONLY verdict equivalence to prevent splits.
        """
        if tx_id not in self.transactions:
            raise gl.vm.UserError("Escrow transaction not found")

        tx = self.transactions[tx_id]
        if tx.settled:
            raise gl.vm.UserError("Escrow already settled")
        if tx.status not in ["SUBMITTED", "DISPUTED"]:
            raise gl.vm.UserError(f"Escrow not ready for AI adjudication (current state: {tx.status})")

        # Compile static evidence variables to capture in nondet scopes
        description = tx.description
        
        seller_statement = tx.seller_evidence.statement
        seller_urls = [str(u) for u in tx.seller_evidence.urls]
        
        buyer_submitted = tx.buyer_evidence.submitted
        buyer_statement = tx.buyer_evidence.statement
        buyer_urls = [str(u) for u in tx.buyer_evidence.urls]

        def leader_fn():
            # Gather and render seller's proof files
            seller_rendered = []
            for url in seller_urls:
                try:
                    body = gl.nondet.web.render(url, mode="text")
                    seller_rendered.append(f"[{url}]: {body[:3000]}")
                except Exception as e:
                    seller_rendered.append(f"[{url}]: Evidence fetch error ({str(e)})")

            # Gather and render buyer's dispute files
            buyer_rendered = []
            for url in buyer_urls:
                try:
                    body = gl.nondet.web.render(url, mode="text")
                    buyer_rendered.append(f"[{url}]: {body[:3000]}")
                except Exception as e:
                    buyer_rendered.append(f"[{url}]: Evidence fetch error ({str(e)})")

            # Compile semantic adjudication prompt
            prompt = "You are a neutral blockchain escrow adjudicator.\n"
            prompt += f"Escrow Transaction Agreement Description: \"{description}\"\n\n"
            
            prompt += f"--- SELLER CLAIMS & EVIDENCE ---\n"
            prompt += f"Seller Statement: \"{seller_statement}\"\n"
            prompt += f"Seller Evidence Pages:\n" + "\n".join(seller_rendered) + "\n\n"
            
            if buyer_submitted:
                prompt += f"--- BUYER CLAIMS & EVIDENCE ---\n"
                prompt += f"Buyer Statement: \"{buyer_statement}\"\n"
                prompt += f"Buyer Evidence Pages:\n" + "\n".join(buyer_rendered) + "\n\n"
            else:
                prompt += "--- BUYER CLAIMS ---\nNo formal counter-evidence submitted by buyer.\n\n"

            prompt += "Evaluate both statements and all fetched web evidence symmetrically.\n"
            prompt += "Decide strictly one of two outcomes based on objective evidence:\n"
            prompt += "- \"DELIVERED\": Evidence confirms the seller completed the transaction terms.\n"
            prompt += "- \"NOT_DELIVERED\": Evidence does not confirm delivery, contradicts it, or is insufficient.\n\n"
            prompt += "Return ONLY raw JSON, no markdown fences:\n"
            prompt += "{\"verdict\": \"DELIVERED\" | \"NOT_DELIVERED\", \"confidence\": <0-100>, \"reason\": \"<brief justification>\"}\n"

            raw_out = gl.nondet.exec_prompt(prompt, response_format="json")

            try:
                if isinstance(raw_out, dict):
                    parsed = raw_out
                else:
                    cleaned = str(raw_out).strip()
                    if cleaned.startswith("```json"):
                        cleaned = cleaned[7:]
                    if cleaned.startswith("```"):
                        cleaned = cleaned[3:]
                    if cleaned.endswith("```"):
                        cleaned = cleaned[:-3]
                    parsed = json.loads(cleaned.strip())

                verdict = str(parsed.get("verdict", "")).strip().upper()
                if verdict not in ["DELIVERED", "NOT_DELIVERED"]:
                    verdict = "NOT_DELIVERED"

                try:
                    conf = int(parsed.get("confidence", 0))
                    if not (0 <= conf <= 100):
                        conf = 0
                except Exception:
                    conf = 0

                return {
                    "verdict": verdict,
                    "confidence": conf,
                    "reason": str(parsed.get("reason", ""))
                }
            except Exception as e:
                return {
                    "verdict": "NOT_DELIVERED",
                    "confidence": 0,
                    "reason": f"Failed to parse AI response: {str(e)}"
                }

        def validator_fn(leader_res) -> bool:
            """
            Validator check: checks only verdict equivalence and confidence category.
            By not requiring exact integer matching of confidence score, 
            it eliminates validation abort splits on minor confidence differences.
            """
            if not isinstance(leader_res, gl.vm.Return):
                return False

            leader_payload = leader_res.calldata
            if not isinstance(leader_payload, dict):
                return False

            leader_verdict = str(leader_payload.get("verdict", "")).strip().upper()
            if leader_verdict not in ["DELIVERED", "NOT_DELIVERED"]:
                return False

            try:
                leader_conf = int(leader_payload.get("confidence", -1))
                if not (0 <= leader_conf <= 100):
                    return False
            except Exception:
                return False

            # Run validator's independent evaluation
            try:
                my_res = leader_fn()
            except Exception:
                return False

            my_verdict = str(my_res.get("verdict", "")).strip().upper()
            try:
                my_conf = int(my_res.get("confidence", -1))
                if not (0 <= my_conf <= 100):
                    return False
            except Exception:
                return False

            # Harden consensus: match binary verdict, and match dispute gate (>=60 threshold)
            if my_verdict != leader_verdict:
                return False
            return (my_conf >= 60) == (leader_conf >= 60)

        # Run non-deterministic consensus
        ruling = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)
        result = _extract_result(ruling)

        verdict = str(result.get("verdict", "NOT_DELIVERED")).strip().upper()
        if verdict not in ["DELIVERED", "NOT_DELIVERED"]:
            verdict = "NOT_DELIVERED"
        try:
            confidence = int(result.get("confidence", 0))
        except Exception:
            confidence = 0
        reason = str(result.get("reason", ""))

        tx.verdict = verdict
        tx.confidence = bigint(confidence)
        tx.verdict_reason = reason

        # Transition to DISPUTED if confidence is too low to settle
        if confidence < 60:
            tx.status = "DISPUTED"
            tx.verdict_reason += " (Adjudication tentative, confidence too low to settle)"
            self.transactions[tx_id] = tx
            return

        tx = self._settle(tx, verdict, reason, confidence)
        self.transactions[tx_id] = tx

    @gl.public.write
    def retry_resolution(self, tx_id: str) -> None:
        """
        Replay settlement without running AI adjudication again.
        Ensures users can recover escrow funds if a native transfer failed transiently.
        """
        if tx_id not in self.transactions:
            raise gl.vm.UserError("Escrow transaction not found")

        tx = self.transactions[tx_id]
        sender = _to_address(gl.message.sender_address)
        
        # Only interested parties or the contract owner can trigger a replay
        if sender != tx.buyer and sender != tx.seller and sender != self.owner:
            raise gl.vm.UserError("Unauthorized; only buyer, seller, or owner can retry resolution")
        if tx.settled:
            raise gl.vm.UserError("Escrow already settled")
        if tx.status not in ["PAYOUT_FAILED", "REFUND_FAILED"]:
            raise gl.vm.UserError(f"Cannot retry resolution in state: {tx.status}")
        if tx.verdict not in ["DELIVERED", "NOT_DELIVERED"]:
            raise gl.vm.UserError("No verdict available to settle")

        tx = self._settle(tx, tx.verdict, tx.verdict_reason, int(tx.confidence))
        self.transactions[tx_id] = tx

    @gl.public.write
    def claim_timeout_refund(self, tx_id: str) -> None:
        """
        Enforce expiration: Buyer claims locked funds if the seller misses the submission deadline.
        Must be called after the deadline timestamp.
        """
        if tx_id not in self.transactions:
            raise gl.vm.UserError("Escrow transaction not found")

        tx = self.transactions[tx_id]
        sender = _to_address(gl.message.sender_address)
        if sender != tx.buyer and sender != self.owner:
            raise gl.vm.UserError("Only the buyer or owner can claim a timeout refund")
        if tx.settled:
            raise gl.vm.UserError("Escrow already settled")
        if tx.status not in ["PENDING_DELIVERY", "DISPUTED"]:
            raise gl.vm.UserError(f"Cannot claim timeout refund in state: {tx.status}")
        if _now_ts() <= tx.deadline:
            raise gl.vm.UserError("The escrow deadline has not yet passed")

        tx = self._settle(
            tx,
            "NOT_DELIVERED",
            "Seller missed the evidence submission deadline; automatic timeout refund executed.",
            100
        )
        self.transactions[tx_id] = tx

    @gl.public.view
    def get_transaction(self, tx_id: str) -> str:
        """Returns detailed JSON representation of a single escrow transaction."""
        if tx_id not in self.transactions:
            raise gl.vm.UserError("Escrow transaction not found")

        tx = self.transactions[tx_id]
        
        res = {
          "tx_id": tx_id,
          "buyer": _addr_str(tx.buyer),
          "seller": _addr_str(tx.seller),
          "description": tx.description,
          "amount": str(tx.amount),
          "deadline": str(int(tx.deadline)),
          "status": tx.status,
          "verdict": tx.verdict,
          "verdict_reason": tx.verdict_reason,
          "confidence": int(tx.confidence),
          "settled": bool(tx.settled),
          "seller_evidence": {
              "submitted": bool(tx.seller_evidence.submitted),
              "urls": [str(u) for u in tx.seller_evidence.urls],
              "statement": tx.seller_evidence.statement,
              "timestamp": str(int(tx.seller_evidence.timestamp))
          },
          "buyer_evidence": {
              "submitted": bool(tx.buyer_evidence.submitted),
              "urls": [str(u) for u in tx.buyer_evidence.urls],
              "statement": tx.buyer_evidence.statement,
              "timestamp": str(int(tx.buyer_evidence.timestamp))
          }
        }
        return json.dumps(res)

    @gl.public.view
    def list_transactions(self, status_filter: str) -> str:
        """Returns JSON list of transactions, optionally filtered by status."""
        results = []
        n = int(self.tx_counter)
        for i in range(n):
            tid = str(i)
            if tid in self.transactions:
                tx = self.transactions[tid]
                if status_filter == "" or tx.status == status_filter:
                    results.append({
                        "tx_id": tid,
                        "buyer": _addr_str(tx.buyer),
                        "seller": _addr_str(tx.seller),
                        "description": tx.description,
                        "amount": str(tx.amount),
                        "deadline": str(int(tx.deadline)),
                        "status": tx.status,
                        "verdict": tx.verdict,
                        "settled": bool(tx.settled)
                    })
        return json.dumps(results)

    @gl.public.view
    def get_count(self) -> int:
        """Returns the total number of escrows created."""
        return int(self.tx_counter)

    @gl.public.view
    def get_owner(self) -> str:
        """Returns the address of the contract owner."""
        return _addr_str(self.owner)
