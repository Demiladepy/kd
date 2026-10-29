#!/usr/bin/env python3
import os
import sys
from dotenv import load_dotenv
from web3 import Web3

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.chain import ChainClient


def main():
    load_dotenv()
    
    try:
        chain = ChainClient()
        print("Treasury address:", chain.account.address)
        
        # Get balances
        eth_balance = chain.get_eth_balance()
        usdc_balance = chain.get_usdc_balance()
        print(f"ETH balance: {Web3.from_wei(eth_balance, 'ether')} ETH")
        print(f"USDC balance: {usdc_balance / 10**6} USDC")
        
        # Send 1 USDC to supplier wallet 1
        supplier = "0xSUPPLIER_WALLET_1"
        print(f"\nSending 1 USDC to {supplier}...")
        
        import asyncio
        result = asyncio.run(chain.transfer_usdc(supplier, "1"))
        tx_hash = result["tx_hash"]
        print(f"Transaction sent: {tx_hash}")
        print(f"Explorer: https://sepolia.basescan.org/tx/{tx_hash}")
        
        print("\nWaiting for receipt...")
        receipt_result = asyncio.run(chain.wait_for_receipt(tx_hash, timeout=120))
        if receipt_result.get("timeout"):
            print("Timeout waiting for receipt")
            sys.exit(1)
        elif receipt_result.get("status") == 1:
            print("Transaction mined successfully! Status: 1")
            sys.exit(0)
        else:
            print(f"Transaction failed! Status: {receipt_result.get('status')}")
            sys.exit(1)
            
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
