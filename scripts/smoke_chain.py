#!/usr/bin/env python3
"""Phase 3: repeat the Phase 0 gate through server.chain.ChainClient.

Same code path the tools use, so a pass here means settlement can work.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from scripts.gate_send_usdc import main

if __name__ == "__main__":
    load_dotenv()
    asyncio.run(main())
