import json
from typing import Any
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.utils import new_agent_text_message
from openai import AsyncOpenAI

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client

from a2a_agent.settings import Settings
from a2a_agent.tools import execute_bash_command

settings = Settings()

class SiteCheckAgentExecutor(AgentExecutor):
    def __init__(self):
        self.client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.openrouter_api_key.get_secret_value(),
        )
        self.model = settings.extraction_model

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        context_text = self._extract_text(context)
        
        await event_queue.enqueue_event(
            new_agent_text_message("Agent Online. Analyzing context and auditing site condition...")
        )

        messages = [
            {"role": "system", "content": self._get_system_prompt()},
            {"role": "user", "content": f"Context: {context_text}"},
        ]

        # Multi-step tool loop
        for _ in range(5):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,  # type: ignore
                    tools=self._get_tools(), # type: ignore
                )
                choice = response.choices[0].message
                messages.append(choice) # type: ignore

                if choice.tool_calls:
                    for tool_call in choice.tool_calls:
                        result = await self._dispatch_tool(tool_call, event_queue)
                        # Relay the direct MCP response as the final step if it was the pipeline
                        if tool_call.function.name == "run_site_check_pipeline":
                            await event_queue.enqueue_event(new_agent_text_message(result))
                        
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": result
                        })
                else:
                    await event_queue.enqueue_event(
                        new_agent_text_message(f"✅ {choice.content or 'Analysis complete.'}")
                    )
                    break
            except Exception as e:
                await event_queue.enqueue_event(
                    new_agent_text_message(f"❌ Process Error: {str(e)}")
                )
                break

    def _extract_text(self, context: RequestContext) -> str:
        text = ""
        if hasattr(context.message, "parts"):
            for part in context.message.parts:
                if hasattr(part, "text") and part.text:
                    text += part.text + "\n"
        elif hasattr(context.message, "text") and context.message.text:
            text = context.message.text
        return text

    def _get_system_prompt(self) -> str:
        return (
            "You are a sophisticated real estate due diligence subagent. "
            "You have access to a local bash shell and a custom SiteCheck pipeline. "
            "Use 'execute_bash_command' to read files or search documents. "
            "If you find unstructured addresses, call 'run_site_check_pipeline' to perform the aerial audit."
        )

    def _get_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "execute_bash_command",
                    "description": "Run any terminal command via bash. Use for file searching or complex parsing.",
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
                            },
                            "analysis_prompt": {
                                "type": "string",
                                "description": "MANDATORY: Specific question for the vision model (e.g., 'Check for roof damage')."
                            },
                            "analysis_schema": {
                                "type": "string",
                                "description": "MANDATORY: JSON schema for the expected vision output."
                            }
                        },
                        "required": ["addresses", "analysis_prompt", "analysis_schema"],
                    },
                },
            },
        ]

    async def _dispatch_tool(self, tool_call: Any, event_queue: EventQueue) -> str:
        name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)

        if name == "execute_bash_command":
            await event_queue.enqueue_event(new_agent_text_message(f"🛠️ Executing Bash: `{args['command']}`"))
            return await execute_bash_command(args["command"])

        if name == "run_site_check_pipeline":
            num_sites = len(args['addresses'])
            await event_queue.enqueue_event(new_agent_text_message(f"🚀 Auditing {num_sites} locations..."))
            
            try:
                async with sse_client(settings.mcp_server_url) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        result = await session.call_tool("process_locations_batch", args)
                        # MCP tool returns content list
                        return result.content[0].text
            except Exception as e:
                return f"MCP Network Error: {str(e)}"
        
        return f"Unknown tool: {name}"
