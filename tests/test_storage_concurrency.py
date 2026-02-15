import os
import time
import shutil
import multiprocessing
from pathlib import Path
from server.storage.storage import Storage

TEST_DIR = Path("./test_concurrency_storage")
KEY = ["counter"]

def worker_increment(num_increments):
    """Increment a shared counter in storage."""
    # Each worker gets its own storage instance (to simulate separate processes/connections)
    storage = Storage(base_dir=str(TEST_DIR))
    
    for _ in range(num_increments):
        def increment(data):
            val = data.get("value", 0)
            data["value"] = val + 1
            # Add a tiny sleep to increase race condition probability if locking is missing
            # time.sleep(0.001) 
        
        storage.update(KEY, increment)

def run_test():
    # Setup
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR)
    TEST_DIR.mkdir()
    
    # Initialize counter
    storage = Storage(base_dir=str(TEST_DIR))
    storage.write(KEY, {"value": 0})
    
    num_processes = 4
    increments_per_process = 50
    expected_total = num_processes * increments_per_process
    
    print(f"Starting {num_processes} processes, each incrementing {increments_per_process} times...")
    
    processes = []
    for _ in range(num_processes):
        p = multiprocessing.Process(target=worker_increment, args=(increments_per_process,))
        processes.append(p)
        p.start()
        
    for p in processes:
        p.join()
        
    # Verify
    final_data = storage.read(KEY)
    final_value = final_data.get("value", 0)
    
    print(f"Final value: {final_value}")
    print(f"Expected:    {expected_total}")
    
    if final_value == expected_total:
        print("SUCCESS: Count matches (Locking worked)")
    else:
        print("FAILURE: Count mismatch (Race conditions occurred)")
        
    # Cleanup
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR)

if __name__ == "__main__":
    run_test()
