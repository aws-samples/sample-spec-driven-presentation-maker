#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""PPTX to JSON CLI wrapper - backward compatible entry point."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sdpm.converter import main

if __name__ == "__main__":
    main()
