# Site Check Pipeline 🔭

Automated OSINT pipeline containing an A2A-compatible custom agent and an MCP server, inspired by legal use cases.

## Motivation

This project was inspired by legal use cases, but could have applications in other domains, too.

**Example use:**

When completing an M&A, lawyers often have to manually review thousands of property locations.

If they are using a legal agent to assist in their work, they can hook it up to our A2A agent and use it as a subagent. The main agent sends our subagent documents containing a set of addresses together with instructions on what to inspect.

Our agent will then, either by scripting or manually, transform the data into a suitable format. It'll also create an optimized image-analysis prompt and a JSON schema containing fields for al the requested information.

Then, it'll pipe these inputs into our custom MCP, which then runs an analysis of all the locations in parallel. It uses Google Maps and Google Street View to obtain images of every site. These images are all analyzed by a VLM based on the input prompt. The results are returned in JSON conforming to input schema using structured generation. The MCP then converts the results into human-friendly Excel and machine-readable JSONL format, which the subagent relays back over to the main agent.

## Architecture & workflow

Using our A2A server as a subagent of a main agent, we'd have the following architecture:

```text
┌──────────────────┐      1. Messy Text     ┌────────────────┐      2. Clean JSON      ┌──────────────┐
│  MAIN AGENT      │───────────────────────>│   SUBAGENT     │────────────────────────>│  SITE CHECK  │
│ (e.g. OpenHands) │<───────────────────────│  (A2A Server)  │<────────────────────────│  MCP SERVER  │
└──────────────────┘      4. Full Report    └────────────────┘      3. JSON Result     └──────────────┘
                         (Relayed)                                (from Tools)
```

The MCP server can be used in a standalone fashion, but we use an A2A compatible agent as the entrypoint for the site check pipeline. This agent transforms the data into a format compatible with the MCP server and generates a suitable prompt and JSON schema for structured generation as inputs for the MCP. The A2A server can be used as a subagent for a main agent instead of using the MCP directly. This spares the main agents context from the tokens used for preparing the data and other inputs for the MCP.

## Get it up and running


### Get it up and running

You'll need a GCP API key with the [Street View static API](https://console.cloud.google.com/marketplace/product/google/street-view-image-backend.googleapis.com) enabled.

To get the dataset, you also need the [Kaggle CLI](https://www.kaggle.com/docs/api).

```bash
# 1. Setup Env
cp .env.sample .env # Fill in GCP_API_KEY and OPENROUTER_API_KEY

# 2. Launch Sandbox
docker-compose up
```

## Try it out

### Integration test

Everything except preparing the API keys is automated in:

```bash
uv run integration_test_ma_deal.py --env-file local.env
```

### Sample M&A dataset

First, you need some data.

To simulate a real-world M&A due diligence scenario (with 1,781 locations), you can use the [Target Store Dataset from Kaggle](https://www.kaggle.com/datasets/ben1989/target-store-dataset) (You'll need the Kaggle CLI tool, or download through your browser):

```bash
# Download and prepare dataset
kaggle datasets download -d ben1989/target-store-dataset
unzip target-store-dataset.zip
mv target.csv data/target_locations.csv
```

### Hook up your main agent

To connect an external agent (like Codex or a custom orchestrator) to this pipeline, point it to the A2A endpoint:

- **Endpoint**: `http://localhost:8000/`
- **Protocol**: A2A (JSON-RPC 2.0)

The main agent will hopefully know what to do.

### ...or manually trigger the audit via A2A over curl

If you are your own main agent, you can also use the A2A manually through curl.

```bash
curl -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "message/send",
    "params": {
      "message": {
        "role": "user",
        "parts": [{
          "kind": "text",
          "text": "Verify these properties from the contract: 1901 E Madison St, Seattle and 401 Biscayne Blvd, Miami."
        }],
        "messageId": "msg-001"
      }
    },
    "id": 1
  }'
```
