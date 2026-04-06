# /// script
# dependencies = [
#   "pandas",
#   "requests",
#   "tqdm",
#   "python-on-whales",
# ]
# ///
"""
M&A Due Diligence Integration Test

This script simulates a real-world real estate audit for an M&A deal.
Execution Flow:
1. Infrastructure Boot: Uses the Docker Compose SDK (python-on-whales) to build and start services.
2. Data Extraction: Loads the local CSV (data/target_locations.csv) and extracts physical store addresses.
3. A2A Request: Sends a standardized A2A message to the Subagent.
4. Verification: Receives the final report paths and prints the status.
5. Cleanup: Automatically tears down containers on completion.
"""
import asyncio
import argparse
import os
import json
import time
import socket
import pandas as pd
import requests
from python_on_whales import docker
import subprocess
import datetime

A2A_URL = "http://localhost:8000/"

def wait_for_port(port, host='localhost', timeout=120.0):
    """Wait until the HTTP service is responding."""
    start_time = time.perf_counter()
    import requests
    while True:
        try:
            r = requests.get(f"http://{host}:{port}/docs", timeout=1)
            if r.status_code:
                print(f"✅ Service is up on port {port}")
                return True
        except requests.exceptions.RequestException:
            pass
            
        time.sleep(2)
        if time.perf_counter() - start_time > timeout:
            return False

async def run_ma_due_diligence_test(max_locations: int = 50):
    print("=" * 70)
    print("MOCK M&A DEAL: Amazon is acquiring Target")
    print("Legal Due Diligence: Verifying store locations via A2A Subagent")
    print("=" * 70)

    dataset_path = "data/target_locations.csv"
    addresses = []

    if os.path.exists(dataset_path):
        print(f"Loading locations from {dataset_path}...")
        df = pd.read_csv(dataset_path, encoding="latin1")
        # Extract addresses from the Kaggle dataset format
        for _, row in df.head(max_locations).iterrows():
            addr = f"{row['Address.FormattedAddress']}, {row['Address.City']}, {row['Address.Subdivision']}"
            addresses.append(addr)
    else:
        print(f"⚠️ Dataset not found at {dataset_path}, using mock addresses.")
        addresses = ["1901 E Madison St, Seattle, WA 98122", "401 Biscayne Blvd, Miami, FL 33132"]

    task_text = f"Perform a due diligence audit on these Target locations: {', '.join(addresses)}"
    
    print(f"\n🚀 Sending Task to A2A Agent ({len(addresses)} locations)...")
    payload = {
        "jsonrpc": "2.0",
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": task_text}],
                "messageId": "msg-ma-test"
            }
        },
        "id": 1
    }

    try:
        # Increase timeout as the audit might take some time
        response = requests.post(A2A_URL, json=payload, timeout=600)
        response.raise_for_status()
        print("\n✅ RECEIVED RESPONSE FROM SUBAGENT:")
        print(json.dumps(response.json(), indent=2))
    except Exception as e:
        print(f"❌ Request failed: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    os.makedirs("logs", exist_ok=True)
    session_log = f"logs/session_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    print(f"📝 Logging session to {session_log}")
    
    print("🐳 Starting Docker containers via Compose SDK...")
    try:
        # Build and start in detached mode
        docker.compose.up(detach=True, build=True)
        
        # Start following logs in the background and write to timestamped file while printing them
        log_process = subprocess.Popen(
            f"docker compose logs -f 2>&1 | tee {session_log}", 
            shell=True
        )
        
        if wait_for_port(8000):
            asyncio.run(run_ma_due_diligence_test(max_locations=args.limit))
        else:
            print("❌ Timeout waiting for services.")
            
    finally:
        user_input = input("\nDo you want to shut down the containers? (y/N): ")
        if user_input.lower() == 'y':
            print("🐳 Tearing down Docker containers...")
            docker.compose.down()
            
        if 'log_process' in locals():
            log_process.terminate()
