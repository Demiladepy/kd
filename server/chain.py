import asyncio
import os
from decimal import Decimal
from typing import Dict, Any, Optional
from web3 import Web3
from web3.exceptions import TimeExhausted


class ChainClient:
    def __init__(self, rpc_url: str = None, private_key: str = None, usdc_address: str = None):
        self.rpc_url = rpc_url or os.getenv("BASE_SEPOLIA_RPC", "https://sepolia.base.org")
        self.private_key = private_key or os.getenv("TREASURY_PRIVATE_KEY")
        self.usdc_address = Web3.to_checksum_address(usdc_address or os.getenv("USDC_ADDRESS", "0x036CbD53842c5426634e7929541eC2318f3dCF7e"))
        
        if not self.private_key:
            raise ValueError("TREASURY_PRIVATE_KEY not set")
        if self.private_key.startswith("0x"):
            pass
        else:
            self.private_key = "0x" + self.private_key
        
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        self.account = self.w3.eth.account.from_key(self.private_key)
        self.chain_id = 84532  # Base Sepolia
        
        # ERC20 ABI for transfer and balanceOf
        self.erc20_abi = [
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function"
            },
            {
                "constant": False,
                "inputs": [
                    {"name": "_to", "type": "address"},
                    {"name": "_value", "type": "uint256"}
                ],
                "name": "transfer",
                "outputs": [{"name": "", "type": "bool"}],
                "type": "function"
            }
        ]
        self.usdc_contract = self.w3.eth.contract(address=self.usdc_address, abi=self.erc20_abi)
        self._nonce_lock = asyncio.Lock()
    
    def get_eth_balance(self, address: str = None) -> int:
        addr = address or self.account.address
        return self.w3.eth.get_balance(Web3.to_checksum_address(addr))
    
    def get_usdc_balance(self, address: str = None) -> int:
        addr = address or self.account.address
        return self.usdc_contract.functions.balanceOf(Web3.to_checksum_address(addr)).call()
    
    async def transfer_usdc(self, to_address: str, amount_usdc: str) -> Dict[str, Any]:
        # amount_usdc is string like "12" -> 12 * 10^6
        amount_decimal = Decimal(amount_usdc)
        amount_base_units = int(amount_decimal * Decimal(10**6))
        to_addr = Web3.to_checksum_address(to_address)
        
        async with self._nonce_lock:
            nonce = self.w3.eth.get_transaction_count(self.account.address)
            
            # Build transaction
            tx = self.usdc_contract.functions.transfer(to_addr, amount_base_units).build_transaction({
                'chainId': self.chain_id,
                'gas': 100000,  # Estimate or set reasonable gas
                'gasPrice': self.w3.eth.gas_price,
                'nonce': nonce,
            })
            
            # Sign transaction
            signed_tx = self.w3.eth.account.sign_transaction(tx, self.private_key)
            # Send transaction
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            tx_hash_hex = tx_hash.hex()
            if not tx_hash_hex.startswith('0x'):
                tx_hash_hex = '0x' + tx_hash_hex
            
            return {"tx_hash": tx_hash_hex}
    
    async def wait_for_receipt(self, tx_hash: str, timeout: int = 45) -> Dict[str, Any]:
        try:
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)
            return {
                "status": receipt['status'],  # 1 for success, 0 for failure
                "block_number": receipt['blockNumber'],
                "receipt": receipt
            }
        except TimeExhausted:
            return {"status": None, "timeout": True}
    
    async def get_transaction_receipt(self, tx_hash: str) -> Optional[Dict[str, Any]]:
        try:
            receipt = self.w3.eth.get_transaction_receipt(tx_hash)
            return {
                "status": receipt['status'],
                "block_number": receipt['blockNumber']
            }
        except Exception:
            return None
