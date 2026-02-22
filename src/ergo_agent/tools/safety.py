"""
Safety layer for AI agent actions on Ergo.

Protects against runaway agents, misconfigured bots, and accidental fund drainage.
All ErgoToolkit actions pass through SafetyConfig validation before execution.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field


class SafetyViolation(Exception):
    """Raised when an agent action violates the configured safety rules."""
    pass


@dataclass
class SafetyConfig:
    """
    Configuration for agent spending limits and operational boundaries.

    Args:
        max_erg_per_tx:       Hard cap on ERG per single transaction
        max_erg_per_day:      Rolling 24h cap on total ERG spent
        allowed_contracts:    Whitelist of allowed interaction targets.
                              Use protocol names ("spectrum", "sigmausd", "rosen")
                              or raw Ergo addresses.
        rate_limit_per_hour:  Max number of state-changing actions per hour
        dry_run:              If True, build transactions but never submit them
    """
    max_erg_per_tx: float = 10.0
    max_erg_per_day: float = 50.0
    allowed_contracts: list[str] = field(default_factory=lambda: ["spectrum", "sigmausd", "rosen", "privacy_pool"])
    rate_limit_per_hour: int = 20
    dry_run: bool = False
    min_withdrawal_delay_blocks: int = 100  # [FIX 3.1] Recommended delay between deposit and withdrawal
    min_pool_ring_size: int = 4  # [FIX 1.1] Minimum ring size for withdrawal

    # Internal tracking (not user-facing)
    _action_timestamps: deque = field(default_factory=deque, repr=False)
    _daily_spend_log: list[tuple[float, float]] = field(default_factory=list, repr=False)  # (timestamp, erg)
    _deposit_heights: dict[str, int] = field(default_factory=dict, repr=False)  # pool_id -> deposit height

    def validate_send(self, amount_erg: float, destination: str) -> None:
        """
        Validate a send action. Raises SafetyViolation if any limit is exceeded.

        Args:
            amount_erg: amount to send in ERG
            destination: target address or protocol name
        """
        # Per-transaction cap
        if amount_erg > self.max_erg_per_tx:
            raise SafetyViolation(
                f"Transaction amount {amount_erg:.4f} ERG exceeds per-tx limit "
                f"of {self.max_erg_per_tx:.4f} ERG."
            )

        # Daily rolling cap
        daily_total = self._get_daily_total()
        if daily_total + amount_erg > self.max_erg_per_day:
            raise SafetyViolation(
                f"Transaction would exceed daily limit: "
                f"{daily_total:.4f} + {amount_erg:.4f} > {self.max_erg_per_day:.4f} ERG."
            )

        # Contract whitelist
        if self.allowed_contracts:
            allowed = self.allowed_contracts
            is_allowed = (
                destination in allowed
                or any(dest.lower() in destination.lower() for dest in allowed)
                or destination.startswith("9")  # mainnet P2PK addresses
                or destination.startswith("3")  # testnet P2PK addresses
            )
            if not is_allowed:
                raise SafetyViolation(
                    f"Destination '{destination}' is not in the allowed contracts list: {allowed}"
                )

    def validate_rate_limit(self) -> None:
        """Check that the agent hasn't exceeded the hourly action rate."""
        now = time.time()
        cutoff = now - 3600  # 1 hour ago

        # Remove old timestamps
        while self._action_timestamps and self._action_timestamps[0] < cutoff:
            self._action_timestamps.popleft()

        if len(self._action_timestamps) >= self.rate_limit_per_hour:
            raise SafetyViolation(
                f"Rate limit exceeded: {self.rate_limit_per_hour} actions/hour."
            )

    def record_action(self, erg_spent: float = 0.0) -> None:
        """Record a completed action for rate limiting and daily spend tracking."""
        now = time.time()
        self._action_timestamps.append(now)
        if erg_spent > 0:
            self._daily_spend_log.append((now, erg_spent))

    def get_status(self) -> dict[str, float | int | bool]:
        """Return current safety status for agent awareness."""
        return {
            "daily_erg_spent": self._get_daily_total(),
            "daily_erg_remaining": max(0.0, self.max_erg_per_day - self._get_daily_total()),
            "actions_last_hour": len(self._action_timestamps),
            "actions_remaining_this_hour": max(0, self.rate_limit_per_hour - len(self._action_timestamps)),
            "dry_run": self.dry_run,
        }

    def _get_daily_total(self) -> float:
        """Sum ERG spent in the last 24 hours, pruning old entries."""
        cutoff = time.time() - 86400
        # Prune entries older than 24h to prevent unbounded growth
        self._daily_spend_log = [(ts, erg) for ts, erg in self._daily_spend_log if ts > cutoff]
        return sum(erg for _, erg in self._daily_spend_log)

    # ------------------------------------------------------------------
    # Phase V: Privacy Leakage Mitigations
    # ------------------------------------------------------------------

    def recommend_withdrawal_delay(self, deposit_height: int, current_height: int) -> dict[str, int | bool]:
        """
        Recommend whether the user should wait before withdrawing.
        Withdrawing too soon after depositing creates a timing correlation.

        Returns:
            {"safe": bool, "blocks_remaining": int, "recommended_wait": int}
        """
        elapsed = current_height - deposit_height
        return {
            "safe": elapsed >= self.min_withdrawal_delay_blocks,
            "blocks_remaining": max(0, self.min_withdrawal_delay_blocks - elapsed),
            "recommended_wait": self.min_withdrawal_delay_blocks,
        }

    @staticmethod
    def compute_deterministic_change(input_value: int, output_value: int, fee: int) -> int:
        """
        Compute a deterministic change amount that rounds to common denominations
        to prevent fingerprinting via unique change values.

        Instead of sending exact change (e.g., 483917 nanoERG), we round to
        the nearest 0.01 ERG (10_000_000 nanoERG) to blend with other transactions.
        """
        raw_change = input_value - output_value - fee
        if raw_change <= 0:
            return 0
        # Round down to nearest 0.01 ERG (10M nanoERG)
        rounded = (raw_change // 10_000_000) * 10_000_000
        return max(rounded, 1_000_000)  # Minimum box value

    @staticmethod
    def randomize_withdrawal_timing() -> float:
        """
        Return a random delay (in seconds) to add before submitting a withdrawal
        to prevent timing correlation attacks.

        Returns a value between 30 and 300 seconds (0.5–5 minutes).
        """
        import random
        return random.uniform(30.0, 300.0)

    def validate_privacy_withdrawal(
        self,
        pool_ring_size: int,
        deposit_height: int | None,
        current_height: int,
    ) -> list[str]:
        """
        Run privacy-aware pre-flight checks before withdrawal.

        Returns a list of warning strings (empty = all clear).
        """
        warnings = []

        if pool_ring_size < self.min_pool_ring_size:
            warnings.append(
                f"LOW_ANONYMITY: Pool ring size {pool_ring_size} < minimum {self.min_pool_ring_size}. "
                f"Withdrawal may be linkable."
            )

        if deposit_height is not None:
            elapsed = current_height - deposit_height
            if elapsed < self.min_withdrawal_delay_blocks:
                warnings.append(
                    f"TOO_SOON: Only {elapsed} blocks since deposit (minimum {self.min_withdrawal_delay_blocks}). "
                    f"Timing analysis risk."
                )

        return warnings

