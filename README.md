# Site Check Pipeline 🔭

Automated OSINT pipeline containing an A2A-compatible custom agent and an MCP server, inspired by legal use cases.

## Motivation

This project was inspired by legal use cases, but may be useful across many domains.

**Example use:**

When completing an M&A, lawyers often have to manually review thousands of property locations.

If they are using a legal agent to assist in their work, they can hook it up to our A2A agent and use it as a subagent. The main agent sends our subagent documents containing a set of addresses together with instructions on what to inspect.

Our agent will then, either by scripting or manually, transform the data into a suitable format. It'll also create an optimized image-analysis prompt and a JSON schema containing fields for al the requested information. It comes with a pre-configured agent skill for this use case.

Then, the agent pipes these inputs into our custom Site Check MCP, which subsequently runs an analysis of all the locations in parallel. It uses Google Maps and Google Street View to obtain a 360-degree view of every site, ensuring the analysis covers both the property and its immediate surroundings. These images are all analyzed by a VLM based on the input prompt. The results are returned in JSON conforming to input schema using structured generation. The MCP then converts the results into human-friendly Excel and machine-readable JSONL format, which the subagent relays back over to the main agent.

## Architecture & workflow

```text
┌──────────────────┐      1. Messy Text     ┌────────────────┐      2. Clean JSON      ┌──────────────┐
│  MAIN AGENT      │───────────────────────>│   SUBAGENT     │────────────────────────>│  SITE CHECK  │
│ (e.g. OpenHands) │<───────────────────────│  (A2A Server)  │<────────────────────────│  MCP SERVER  │
└──────────────────┘      4. Full Report    └────────────────┘      3. JSON Result     └──────────────┘
                         (Relayed)                                (from Tools)
```

The A2A subagent acts as a bridge, handling the heavy lifting of data preparation and tool orchestration, which saves context and simplifies the main agent's task.

## Environment setup

You'll need a GCP API key with the [Street View static API](https://console.cloud.google.com/marketplace/product/google/street-view-image-backend.googleapis.com) enabled.

```bash
# 1. Setup Env
cp .env.sample .env # Fill in GCP_API_KEY and OPENROUTER_API_KEY

# 2. Launch Services
docker-compose up
```

## Usage

### Sample M&A dataset

The [Target Store Dataset from Kaggle](https://www.kaggle.com/datasets/ben1989/target-store-dataset) containing approx. 2000 locations is included in this repository at `data/target_locations.csv` for demonstration purposes.

### Hook up your main agent

To connect an external agent (like Codex or a custom orchestrator) to this pipeline, point it to the A2A endpoint:

- **Endpoint**: `http://localhost:8000/`
- **Protocol**: A2A (JSON-RPC 2.0)

The main agent will hopefully know what to do.

### ...or manually trigger the audit via A2A over curl

You can trigger the entire pipeline by sending a natural language request to the A2A agent. The agent will use its tools to find the dataset, filter it (e.g., by state), and then run the site audit with real-time feedback.

#### One-Step Streaming Audit (Clean Terminal Demo)

This command pipes the stream into `jq` to show only the agent's real-time updates (like the spinner and progress bars) on a single line.

```bash
curl -sN -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "method": "message/stream",
    "params": {
      "message": {
        "role": "user",
        "parts": [{"kind": "text", "text": "Read data/target_locations.csv. Filter for properties in CA. Run an audit on those locations."
        }],
        "message_id": "msg-001"
      }
    },
    "id": 1
  }' | sed -u 's/^data: //g' | jq -rj --unbuffered '.params | (.. | .text? // empty)'
```

### Integration Test

Run the automated test suite to verify the end-to-end flow:

```bash
uv run integration_test_ma_deal.py --env-file local.env
```
