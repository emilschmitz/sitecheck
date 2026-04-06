# Site Check Pipeline 🔭

Automated OSINT pipeline containing an A2A-compatible custom agent and an MCP server.

## Motivation

This project was inspired by legal use cases 🧑‍⚖️ , but may be useful any domain relying on investigative work on Google Maps.

**Example use:**


https://github.com/user-attachments/assets/e4b3ac17-85b1-460b-951a-28e15a0d2330


When completing an M&A, lawyers often have to manually review thousands of property locations.

If a lawyer is using a legal agent to assist in their work, they can hook it up to this A2A agent and use it as a subagent. The main agent can then our subagent documents containing sets of addresses together with instructions on what to inspect.

Our agent will then, either by scripting or manually, transform the data into a suitable format. It'll also create an optimized image-analysis prompt and a JSON schema with a field for every requested item of information. It comes with a pre-configured agent skill for the M&A use case.

In the next step, the agent pipes these inputs into our custom Sitecheck MCP, which then runs an analysis of all the locations in parallel. It uses Google Maps and Google Street View to obtain a 360-degree view of every site, ensuring the analysis covers both the property and its immediate surroundings. These images are all analyzed by a VLM based on the input prompt. The results are returned in JSON conforming to input schema using structured generation. The MCP then converts the results into human-friendly Excel and machine-readable JSONL format, which the subagent relays back over to the main agent.

## Architecture & workflow

```text
┌──────────────────┐
│    MAIN AGENT    │
│ (e.g. OpenHands) │
└──────────────────┘
    │          ▲
    │ 1. Messy │ 4. Full Report
    │    Text  │    (Relayed)
    ▼          │
┌──────────────────┐
│     SUBAGENT     │
│   (A2A Server)   │
└──────────────────┘
    │          ▲
    │ 2. Clean │ 3. JSON Result
    │    JSON  │    (from Tools)
    ▼          │
┌──────────────────┐
│    SITE CHECK    │
│    MCP SERVER    │
└──────────────────┘
```

The A2A subagent acts as a bridge, handling the heavy lifting of data preparation and tool orchestration, which saves context and simplifies the main agent's task.


## Usage

### Sample M&A dataset

A dataset of [Target Store locations from Kaggle](https://www.kaggle.com/datasets/ben1989/target-store-dataset) is included in this repository at `data/target_locations.csv` for demonstration purposes.

### Environment setup

You'll need a GCP API key with the [Street View static API](https://console.cloud.google.com/marketplace/product/google/street-view-image-backend.googleapis.com) enabled and an API key for an LLM provider (e.g. OpenRouter) to use the pipeline.

Run `cp a2a_agent/.env.sample a2a_agent/.env` and `cp mcp_server/.env.sample mcp_server/.env` and fill in your keys in the `.env` files. You can also specify the `BASE_URL` if you're not using OpenRouter.

### Hooking up your main agent

You can let another agent, like Claude Code, use this pipeline as a subagent. To do that, start the A2A and MCP with `docker-compose up` and point your agent to the A2A endpoint:

- **Endpoint**: `http://localhost:8000/`
- **Protocol**: A2A (JSON-RPC 2.0)

If your main agent speaks A2A, it should know what to do.

### ...or try it out manually via the Interactive Integration Test

If you are your own main agent and would like to use the pipeline manually, the script `integration_test.py` provides an interactive terminal UI for chatting with the agent. This is the best way to verify the pipeline for your use case end-to-end.

```bash
# Run Integration Test
uv run integration_test.py
```

Once in the chat, send in a natural language request like:
> "Read data/target_locations.csv. Check that every location listed in CA exists, check its condition, and availability of parking space."

The runtime should be under a minute for the above prompt. The MCP is heavily optimized and runs all image fetching and analysis in parallel.
