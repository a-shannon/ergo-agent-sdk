"""defi module init"""
from ergo_agent.defi.oracle import ORACLE_NFT_IDS, OracleReader
from ergo_agent.defi.spectrum import WELL_KNOWN_TOKENS, Pool, SpectrumDEX

__all__ = ["OracleReader", "ORACLE_NFT_IDS", "SpectrumDEX", "Pool", "WELL_KNOWN_TOKENS"]
