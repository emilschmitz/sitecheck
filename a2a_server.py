import json

import uvicorn
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps.jsonrpc.fastapi_app import A2AFastAPIApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers.default_request_handler import (
    DefaultRequestHandler,
)
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from a2a.utils import new_agent_text_message
from openai import AsyncOpenAI

from config import A2ASettings
from bash_mcp import execute_command
from mcp_server import process_locations_batch

# Load settings locally
settings = A2ASettings()  # type: ignore

openai_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=settings.openrouter_api_key.get_secret_value(),
)


class SiteCheckAgentExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        document_text: str = context.message.text  # type: ignore
        await event_queue.enqueue_event(
            new_agent_text_message("Agent Online. Analyzing document and preparing tools...")
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a sophisticated real estate due diligence subagent. "
                    "You have access to a bash shell for OSINT/scripting and a custom SiteCheck pipeline. "
                    "If you encounter unstructured text, first extract the addresses. "
                    "Then, call 'run_site_check_pipeline' with those addresses to perform a deep aerial audit."
                ),
            },
            {"role": "user", "content": f"Document text: {document_text}"},
        ]

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "execute_bash_command",
                    "description": "Run any terminal command via bash. Use for file searching, downloading data, or complex parsing.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string", "description": "The command string to execute."}
                        },
                        "required": ["command"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "run_site_check_pipeline",
                    "description": "Trigger the SiteCheck engine on a list of addresses to generate a Vision/OSINT report.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "addresses": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of physical store/property addresses."
                            }
                        },
                        "required": ["addresses"],
                    },
                },
            },
        ]

        # Define a progress callback to pipe MCP updates back to the A2A event queue
        async def progress_report(msg: str):
            await event_queue.enqueue_event(new_agent_text_message(f"📡 {msg}"))

        # Loop to allow multi-step tool usage
        for _ in range(5):
            try:
                response = await openai_client.chat.completions.create(
                    model=settings.extraction_model,
                    messages=messages,  # type: ignore
                    tools=tools,  # type: ignore
                )
                choice = response.choices[0].message
                messages.append(choice)  # type: ignore

                if choice.tool_calls:
                    for tool_call in choice.tool_calls:
                        fn_name = tool_call.function.name
                        fn_args = json.loads(tool_call.function.arguments)

                        if fn_name == "execute_bash_command":
                            await event_queue.enqueue_event(
                                new_agent_text_message(f"🛠️ Executing Bash: `{fn_args['command']}`")
                            )
                            result = await execute_command(fn_args["command"])
                        elif fn_name == "run_site_check_pipeline":
                            num_sites = len(fn_args["addresses"])
                            await event_queue.enqueue_event(
                                new_agent_text_message(f"🚀 Launching SiteCheck Pipeline for {num_sites} locations...")
                            )
                            result = await process_locations_batch(
                                fn_args["addresses"], 
                                dry_run=False, 
                                progress_callback=progress_report
                            )
                        else:
                            result = f"Unknown tool: {fn_name}"

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": result
                        })
                else:
                    # Final answer
                    content = choice.content or "Analysis complete."
                    await event_queue.enqueue_event(new_agent_text_message(f"✅ {content}"))
                    break

            except Exception as e:
                await event_queue.enqueue_event(
                    new_agent_text_message(f"❌ Process Error: {str(e)}")
                )
                break


# 1. Provide an A2A AgentCard
agent_card = AgentCard(
    protocol_version="2024-11-05",  # Mandatory field
    name="SiteCheckSubagent",
    description="An A2A-compliant subagent for extracting locations from legal contracts and auditing their physical store condition.",
    capabilities=AgentCapabilities(),  # Mandatory object
    default_input_modes=["text"],
    default_output_modes=["text"],
    skills=[
        AgentSkill(
            id="extract-and-audit",
            name="extract_and_audit",
            description="Finds addresses from unstructured text and runs the SiteCheck due diligence pipeline.",
        )
    ],
)

# 2. Setup A2A Executor & Handlers
executor = SiteCheckAgentExecutor()
handler = DefaultRequestHandler(agent_executor=executor, task_store=InMemoryTaskStore())

# 3. Create FastAPI app wrapped with A2A SDK
a2a_app = A2AFastAPIApplication(agent_card=agent_card, http_handler=handler)
app = a2a_app.build()


# 4. Custom status route
@app.get("/status")
def get_status():
    has_gcp = bool(settings.gcp_api_key)
    has_or = bool(settings.openrouter_api_key)
    return {
        "status": "online",
        "agent": "SiteCheckSubagent (A2A Protocol)",
        "model": settings.extraction_model,
        "keys": {"GCP_API_KEY": has_gcp, "OPENROUTER_API_KEY": has_or},
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
