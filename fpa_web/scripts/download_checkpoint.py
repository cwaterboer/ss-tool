#!/usr/bin/env python3
"""
Download LingBot-Map checkpoint from HuggingFace Hub.

This script is run during app initialization (local dev or Docker build).
The checkpoint is NOT stored in version control due to its 4.6GB size.

Usage:
    python scripts/download_checkpoint.py

Environment Variables:
    CHECKPOINT_ROOT: Directory to save checkpoints (default: /tmp/checkpoints)
    LINGBOT_CHECKPOINT_PATH: Full path to checkpoint (default: CHECKPOINT_ROOT/lingbot-map.pt)
"""

import os
import sys
from pathlib import Path

def download_checkpoint():
    """Download model checkpoint from HuggingFace Hub."""
    
    # Determine checkpoint path
    checkpoint_dir = os.environ.get(
        'CHECKPOINT_ROOT',
        '/tmp/checkpoints'
    )
    checkpoint_path = os.environ.get(
        'LINGBOT_CHECKPOINT_PATH',
        os.path.join(checkpoint_dir, 'lingbot-map.pt')
    )
    
    # Create directory
    os.makedirs(checkpoint_dir, exist_ok=True)
    
    # Skip if already exists
    if os.path.exists(checkpoint_path):
        size_gb = os.path.getsize(checkpoint_path) / (1024**3)
        print(f"✓ Checkpoint already exists: {checkpoint_path}")
        print(f"  Size: {size_gb:.2f} GB")
        return checkpoint_path
    
    print("=" * 70)
    print("Downloading LingBot-Map Checkpoint from HuggingFace Hub")
    print("=" * 70)
    print(f"Repository: robbyant/lingbot-map")
    print(f"File: lingbot-map.pt (4.6 GB)")
    print(f"Destination: {checkpoint_path}")
    print("")
    print("This is a one-time download. Subsequent runs will use the cached file.")
    print("Estimated time: 10-30 minutes depending on connection speed")
    print("=" * 70)
    
    try:
        from huggingface_hub import hf_hub_download
        
        # Download from HuggingFace
        downloaded_path = hf_hub_download(
            repo_id="robbyant/lingbot-map",
            filename="lingbot-map.pt",
            cache_dir=checkpoint_dir,
            local_dir=checkpoint_dir,
            resume_download=True,
            force_filename="lingbot-map.pt"
        )
        
        size_gb = os.path.getsize(downloaded_path) / (1024**3)
        print("")
        print("=" * 70)
        print("✓ Download Complete!")
        print("=" * 70)
        print(f"Checkpoint saved to: {downloaded_path}")
        print(f"Size: {size_gb:.2f} GB")
        print("")
        print("The app can now run inference with the LingBot-Map model.")
        return downloaded_path
        
    except ImportError:
        print("✗ Error: huggingface_hub not installed")
        print("Install it with: pip install huggingface-hub")
        sys.exit(1)
        
    except Exception as e:
        print(f"✗ Download failed: {e}")
        print("")
        print("Troubleshooting:")
        print("1. Check internet connection")
        print("2. Verify disk space (need ~5GB)")
        print("3. Try again later if HuggingFace is temporarily unavailable")
        print("4. Manual download: https://huggingface.co/robbyant/lingbot-map")
        sys.exit(1)


if __name__ == '__main__':
    download_checkpoint()
