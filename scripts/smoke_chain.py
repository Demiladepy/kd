#!/usr/bin/env python3
import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.gate_send_usdc import main

if __name__ == "__main__":
    main()
