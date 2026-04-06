# /// script
# dependencies = [
#   "requests",
#   "python-on-whales",
# ]
# ///
"""
M&A Due Diligence Integration Test

This script simulates a real-world real estate audit for an M&A deal.
Minimalist version: Offloads all data processing to the Subagent.
"""
import asyncio
import argparse
import os
import json
import time
import requests
from python_on_whales import docker
import subprocess
import datetime

A2A_URL = "http://localhost:8000/"

def wait_for_port(port, host='localhost', timeout=120.0):
    """Wait until the HTTP service is responding."""
    start_time = time.perf_counter()
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

async def run_ma_due_diligence_test(limit: int = 5):
    print("=" * 70)
    print("REAL ESTATE M&A DEAL: Amazon is acquiring Target")
    print("Legal Due Diligence: Verifying store locations via A2A Subagent")
    print("=" * 70)

    dataset_path = "data/target_locations.csv"
    if not os.path.exists(dataset_path):
        print(f"❌ CRITICAL ERROR: Dataset not found at {dataset_path}")
        print("Fail-fast: Exiting test as no real data is available.")
        return

    task_text = (
        f"Read the dataset at {dataset_path}. "
        f"Filter for the first {limit} locations in California (CA). "
        "Perform a due diligence audit on them as specified in your skills."
    )
    
    print(f"\n🚀 Sending Task to A2A Agent (Target: {limit} CA locations)...")
    payload = {
        "jsonrpc": "2.0",
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": task_text}],
                "message_id": "msg-ma-test"
            }
        },
        "id": 1
    }

    try:
        # Increase timeout as the audit might take some time
        response = requests.post(A2A_URL, json=payload, timeout=900)
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
            asyncio.run(run_ma_due_diligence_test(limit=args.limit))
        else:
            print("❌ Timeout waiting for services.")
            
    finally:
        user_input = input("\nDo you want to shut down the containers? (y/N): ")
        if user_input.lower() == 'y':
            print("🐳 Tearing down Docker containers...")
            docker.compose.down()
            
        if 'log_process' in locals():
            log_process.terminate()
