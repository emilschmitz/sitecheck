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

To get the dataset, you also need the [Kaggle CLI](https://www.kaggle.com/docs/api).

```bash
# 1. Setup Env
cp .env.sample .env # Fill in GCP_API_KEY and OPENROUTER_API_KEY

# 2. Launch Services
docker-compose up
```

## Usage

### (Optional) Sample M&A dataset

First, we'll need some data.

To simulate an M&A due diligence scenario, you can use the [Target Store Dataset from Kaggle](https://www.kaggle.com/datasets/ben1989/target-store-dataset) containing approx. 2000 locations (You'll need the Kaggle CLI tool with an API key, or download through your browser):

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
# This will return a Task object with an "id"
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
          "text": "Please read data/sample_contract.txt, filter for all properties in California, and run an audit on those locations to check if there are any obvious signs of exterior damage. Provide a brief summary of the audit results and the generated files when you are done."
        }],
        "messageId": "msg-001"
      }
    },
    "id": 1
  }'
```

#### 2. Track Progress via Stream

Replace `<TASK_ID>` with the ID returned from the previous step. The ID is the `result.id` if you get a `Task` or the `taskId` if you got a `Message`. The `-N` flag in `curl` ensures that the output is not buffered.

```bash
curl -N -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tasks/resubscribe",
    "params": {
      "id": "<TASK_ID>"
    },
    "id": 2
  }'
```

### Integration Test

Run the automated test suite to verify the end-to-end flow:

```bash
uv run integration_test_ma_deal.py --env-file local.env
```
