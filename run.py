#!/usr/bin/env python3
"""mhyscan 入口脚本"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from mhycli.cli import main

if __name__ == "__main__":
    main()
