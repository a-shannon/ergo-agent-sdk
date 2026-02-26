from typing import Any

try:
    from ergo_lib_python.chain import Constant
except ImportError:
    Constant = None  # type: ignore[assignment,misc]

from ergo_agent.core.builder import TransactionBuilder
from ergo_agent.core.node import ErgoNode


class ErgoTreasury:
    """
    Client for interacting with Ergo DAO Treasury or MultiSig wallets.
    Provides methods to build governance proposals, vote on proposals,
    and execute approved multi-sig transactions.
    """

    def __init__(self, node: ErgoNode = None):
        self.node = node or ErgoNode()

    def build_proposal_tx(self, treasury_address: str, target_address: str, amount_erg: float, description: str, wallet: Any) -> dict[str, Any]:
        """
        Build an unsigned transaction that submits a new funding proposal to the DAO.

        Args:
            treasury_address: The P2S address of the Treasury/MultiSig contract
            target_address: The recipient address for the proposed funding
            amount_erg: The amount of ERG requested in the proposal
            description: A short string describing the proposal (stored in R4)
            wallet: The proposer's wallet instance
        """
        # Minimum fee and proposal box value
        proposal_box_erg = 10_000_000 # 0.01 ERG to fund the proposal box

        builder = TransactionBuilder(self.node, wallet)

        # Determine a mock structure for the proposal box (typically its own contract, but for now we send it back to the treasury P2S)
        # We put the requested amount in R4, target_address in R5, description in R6
        registers = {
            "R4": bytes(Constant.from_i64(int(amount_erg * 1e9))).hex(),   # Long: amount requested
            "R5": bytes(Constant(target_address.encode("utf-8"))).hex(), # Coll: target address
            "R6": bytes(Constant(description.encode("utf-8"))).hex()     # Coll: description
        }

        builder.add_output_raw(
            ergo_tree=self.node._resolve_address_to_tree(treasury_address),
            value_nanoerg=proposal_box_erg,
            tokens=[],
            registers=registers
        )

        return builder.build()

    def build_vote_tx(self, proposal_box_id: str, vote: bool, wallet: Any) -> dict[str, Any]:
        """
        Build an unsigned transaction to cast a vote on an active proposal.
        """
        # Voting logic depends on the specific governance token or multi-sig script structure.
        # This is a placeholder for the boilerplate logic.
        raise NotImplementedError("DAO Voting is dependent on specific governance contract state machines.")

    def build_execute_tx(self, proposal_box_id: str, treasury_address: str, wallet: Any) -> dict[str, Any]:
        """
        Build an unsigned transaction to execute a proposal that has reached consensus.
        """
        # Execution logic requires consuming the proposal box, counting votes in context, and sending funds from the treasury.
        raise NotImplementedError("DAO Execution requires complex multi-input verification.")
