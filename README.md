# Site Check Pipeline

Automated OSINT real estate due diligence via A2A (Agent-to-Agent) and MCP (Model Context Protocol).

## 👨‍💼 Motivation

In the context of an M&A, lawyers often have to manually review thousands of property locations. This is an agent that can be integrated as a subagent via A2A so that the main agent can just dump in all the data of the locations without polluting its context with any formatting or anything. The subagent will (through scripting or manually) transform the data into a suitable format and will then pipe it to a custom MCP which will run all the locations in parallel through a data pipeline, checking every building with Google Maps and Google Street View. The MCP will then output an Excel sheet which contains a large table with, for every unit, whether it was detected and the state that it is in, along with a summary next to that.

This is a demo for how A2A can be used to integrate OSINT data processing into legal or other agents in a plug and play fashion.

## 🏗️ Architecture & Workflow

```text
┌──────────────┐      1. Text Dump      ┌────────────────┐      2. Clean JSON      ┌──────────────┐
│  MAIN AGENT  │───────────────────────>│   SUBAGENT     │────────────────────────>│  SITE CHECK  │
│ (e.g. Codex) │<───────────────────────│  (A2A Server)  │<────────────────────────│  MCP SERVER  │
└──────────────┘      5. JSON Summary   └───────┬────────┘      4. Data Reports    └──────────────┘
                                                │
                                                │ 3. Shared Workspace (/data)
                                                ▼
                                        ┌────────────────┐
                                        │    BASH MCP    │ (File Ops, OSINT,
                                        │   (Sandboxed)  │  Python Scripts)
                                        └────────────────┘
```

We use an A2A compatible agent as the entrypoint for the site check pipeline. This agent transforms the data into a format compatible with the MCP server and generates a suitable prompt and JSON schema for structured generation as inputs for the MCP. The A2A server can be used as a subagent for a main agent instead of using the MCP directly. This spares the main a  gents context from the tokens used for preparing the data and other inputs for the MCP.

## 🚀 Quick Start (Sandboxed)

The easiest way to run the pipeline is via Docker Compose, which provides a sandboxed environment with a shared workspace for all agents.

```bash
# 1. Setup Env
cp .env.sample .env # Fill in GCP_API_KEY and OPENROUTER_API_KEY

# 2. Launch Sandbox
docker-compose up --build
```

### Hooking up your Main Agent

To connect an external agent (like Codex or a custom orchestrator) to this pipeline, point it to the A2A endpoint:

- **Endpoint**: `http://localhost:8000/`
- **Protocol**: A2A (JSON-RPC 2.0)

## 🛠️ Manual Testing

### Triggering the Audit via A2A (curl)

Use this to simulate the Main Agent sending a task to the Subagent:

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

**What happens next?**

- The Subagent logs its progress: *"Extracting addresses..."* -> *"Invoking SiteCheck MCP..."*.
- The audit runs in parallel.
- **Result**: You receive a JSON response with absolute paths to the generated `site_check_report.xlsx` (human-readable) and `site_check_report.csv` (machine-readable) in the shared `data/` folder.
