# /// script
# dependencies = [
#   "pandas",
#   "requests",
#   "tqdm",
#   "python-on-whales",
#   "kaggle",
# ]
# ///
"""
M&A Due Diligence Integration Test

This script simulates a real-world real estate audit for an M&A deal.
Execution Flow:
1. Environment Check: Verifies the 'data/' directory exists.
2. Dataset Acquisition: Uses the Kaggle API to download the Target Store Dataset.
3. Infrastructure Boot: Uses the Docker Compose SDK (python-on-whales) to build and start services.
4. Data Extraction: Loads the CSV and extracts physical store addresses.
5. A2A Request: Sends a standardized A2A message to the Subagent.
6. Verification: Receives the final report paths and prints the status.
7. Cleanup: Automatically tears down containers on completion.
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
from kaggle.api.kaggle_api_extended import KaggleApi

A2A_URL = "http://localhost:8000/"

def wait_for_port(port, host='localhost', timeout=120.0):
    """Wait until a port is open."""
    start_time = time.perf_counter()
    while True:
        try:
            with socket.create_connection((host, port), timeout=1):
                print(f"✅ Service is up on port {port}")
                return True
        except (OSError, ConnectionRefusedError):
            time.sleep(2)
            if time.perf_counter() - start_time > timeout:
                return False

def download_dataset():
    dataset_path = "data/target_locations.csv"
    if os.path.exists(dataset_path):
        print(f"✅ Dataset already exists at {dataset_path}")
        return

    print("📥 Downloading Target Store Dataset via Kaggle API...")
    try:
        os.makedirs("data", exist_ok=True)
        api = KaggleApi()
        api.authenticate()
        
        # Download and unzip
        api.dataset_download_file(
            "ben1989/target-store-dataset", 
            file_name="target.csv", 
            path="data"
        )
        
        # Kaggle API downloads it as target.csv.zip, we need to unzip it
        import zipfile
        zip_path = "data/target.csv.zip"
        if os.path.exists(zip_path):
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall("data")
            os.remove(zip_path)
            
        os.rename("data/target.csv", dataset_path)
        print(f"✅ Dataset prepared at {dataset_path}")
    except Exception as e:
        print(f"❌ Kaggle API Error: {e}")
        print("Falling back to small mock sample...")

async def run_ma_due_diligence_test(max_locations: int = 5):
    print("=" * 70)
    print("MOCK M&A DEAL: Amazon is acquiring Target")
    print("Legal Due Diligence: Verifying store locations via A2A Subagent")
    print("=" * 70)

    dataset_path = "data/target_locations.csv"
    addresses = []

    if os.path.exists(dataset_path):
        print(f"Loading locations from {dataset_path}...")
        df = pd.read_csv(dataset_path, encoding="latin1")
        for _, row in df.head(max_locations).iterrows():
            addr = f"{row['Address.FormattedAddress']}, {row['Address.City']}, {row['Address.Subdivision']}"
            addresses.append(addr)
    else:
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

    download_dataset()
    
    print("🐳 Starting Docker containers via Compose SDK...")
    try:
        # Build and start in detached mode
        docker.compose.up(detach=True, build=True)
        
        if wait_for_port(8000):
            asyncio.run(run_ma_due_diligence_test(max_locations=args.limit))
        else:
            print("❌ Timeout waiting for services.")
            
    finally:
        user_input = input("\nDo you want to shut down the containers? (y/N): ")
        if user_input.lower() == 'y':
            print("🐳 Tearing down Docker containers...")
            docker.compose.down()
