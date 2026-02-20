"""
Core data models for the Ergo blockchain.
All amounts are in nanoERG (1 ERG = 1,000,000,000 nanoERG) internally.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

NANOERG_PER_ERG = 1_000_000_000


class Token(BaseModel):
    """A token held in an Ergo box."""
    token_id: str
    amount: int
    name: str | None = None
    decimals: int = 0

    @property
    def amount_display(self) -> float:
        """Human-readable amount adjusted for decimals."""
        return self.amount / (10 ** self.decimals) if self.decimals else self.amount


class Box(BaseModel):
    """An unspent Ergo UTXO box."""
    box_id: str
    value: int  # nanoERG
    ergo_tree: str
    address: str | None = None
    creation_height: int
    index: int = 0
    transaction_id: str | None = None
    tokens: list[Token] = Field(default_factory=list)
    additional_registers: dict[str, Any] = Field(default_factory=dict)

    @property
    def value_erg(self) -> float:
        """ERG value (human-readable)."""
        return self.value / NANOERG_PER_ERG
        
    def decode_register(self, register_id: str) -> Any | None:
        """
        Dynamically decode a raw Box register hex string natively using ergo-lib-python's
        `Constant.from_bytes` schema back into its typed Python equivalent.

        Args:
            register_id: The register to fetch (e.g. 'R4', 'R5')

        Returns:
            The parsed python value, or None if the register is missing or unparseable.
        """
        raw_val = self.additional_registers.get(register_id)
        if not raw_val:
            return None
            
        try:
            # We import here to avoid circular dependencies with models.py
            from ergo_lib_python.chain import Constant
            
            # The Node API returns registers as hex serialized bytes 
            byte_val = bytes.fromhex(raw_val)
            const = Constant.from_bytes(byte_val)
            return const.value
        except Exception:
            # Optionally log decoding errors here in the future
            return None

class Balance(BaseModel):
    """Wallet balance summary."""
    address: str
    erg: float
    erg_nanoerg: int
    tokens: list[Token] = Field(default_factory=list)

    def to_agent_summary(self) -> str:
        """Human-readable summary for the LLM."""
        lines = [f"ERG: {self.erg:.4f}"]
        for token in self.tokens:
            name = token.name or token.token_id[:12] + "..."
            lines.append(f"{name}: {token.amount_display}")
        return ", ".join(lines)


class UnsignedTransaction(BaseModel):
    """An unsigned Ergo transaction ready to be signed."""
    inputs: list[dict[str, Any]]
    outputs: list[dict[str, Any]]
    data_inputs: list[dict[str, Any]] = Field(default_factory=list)
    fee: int = 1_100_000  # nanoERG minimum fee


class Transaction(BaseModel):
    """A submitted or confirmed transaction."""
    tx_id: str
    inputs: list[dict[str, Any]]
    outputs: list[dict[str, Any]]
    confirmed: bool = False
    confirmations: int = 0


class SwapQuote(BaseModel):
    """A DEX swap quote from Spectrum."""
    pool_id: str
    token_in_id: str
    token_in_amount: int
    token_out_id: str
    token_out_amount: int
    price_impact_pct: float
    fee_pct: float

    @property
    def price(self) -> float:
        """Effective exchange rate."""
        return self.token_out_amount / self.token_in_amount if self.token_in_amount else 0.0
