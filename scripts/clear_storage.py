#!/usr/bin/env python3
"""
Clear OpenScrum storage directory to sync with workspace structure.

This script removes all session data from ~/.openscrum/storage/ so that
only sessions with corresponding workspace directories in ~/openscrum/workspaces/
will exist after recreation.
"""

import os
import shutil
from pathlib import Path

def clear_storage():
    """Clear the OpenScrum storage directory."""
    # Default storage root: $OPENSCRUM_DATA/storage or ~/.openscrum/storage
    data_dir = os.environ.get(
        "OPENSCRUM_DATA_DIR",
        os.path.join(os.path.expanduser("~"), ".openscrum"),
    )
    storage_dir = os.path.join(data_dir, "storage")
    
    storage_path = Path(storage_dir)
    
    if not storage_path.exists():
        print(f"Storage directory does not exist: {storage_dir}")
        return
    
    print(f"Clearing storage directory: {storage_dir}")
    
    # Remove all contents
    try:
        for item in storage_path.iterdir():
            if item.is_dir():
                print(f"  Removing directory: {item.name}")
                shutil.rmtree(item)
            else:
                print(f"  Removing file: {item.name}")
                item.unlink()
        
        print(f"\n✓ Storage directory cleared successfully!")
        print(f"  All sessions will need to be recreated.")
        print(f"  Workspace directories in ~/openscrum/workspaces/ are preserved.")
    except Exception as e:
        print(f"\n✗ Error clearing storage: {e}")
        raise

if __name__ == "__main__":
    import sys
    
    # Confirm before clearing
    print("=" * 60)
    print("WARNING: This will delete ALL session data!")
    print("=" * 60)
    print(f"Storage location: ~/.openscrum/storage/")
    print(f"\nThis will remove:")
    print("  - All session metadata")
    print("  - All message history")
    print("  - All session parts/tools")
    print("\nWorkspace directories (~/openscrum/workspaces/) will NOT be affected.")
    
    response = input("\nAre you sure you want to continue? (yes/no): ")
    if response.lower() not in ("yes", "y"):
        print("Cancelled.")
        sys.exit(0)
    
    try:
        clear_storage()
    except KeyboardInterrupt:
        print("\n\nCancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nError: {e}")
        sys.exit(1)
