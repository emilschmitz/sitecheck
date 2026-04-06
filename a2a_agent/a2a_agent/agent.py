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
import logging

settings = Settings()
logger = logging.getLogger(__name__)

class SiteCheckAgentExecutor(AgentExecutor):
    def __init__(self):
        self.client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.openrouter_api_key.get_secret_value(),
        )
        self.model = settings.extraction_model

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        context_text = self._extract_text(context)
        
        # Optional check: usually only full execution environments have task context
        if hasattr(context, "task") and context.task:
            await event_queue.enqueue_event(context.task)

        await event_queue.enqueue_event(
            new_agent_text_message("Agent Online. Analyzing context and auditing site condition...")
        )

        messages = [
            {"role": "system", "content": self._get_system_prompt()},
            {"role": "user", "content": f"Context: {context_text}"},
        ]
        
        logger.info(f"Sending Messages to LLM: {json.dumps(messages, indent=2)}")

        # Multi-step tool loop
        logger.info(f"Agent starting task with extraction model: {self.model}")
        for step in range(5):
            try:
                logger.info(f"--- Step {step + 1} / 5 ---")
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,  # type: ignore
                    tools=self._get_tools(), # type: ignore
                )
                choice = response.choices[0].message
                messages.append(choice) # type: ignore

                if choice.tool_calls:
                    for tool_call in choice.tool_calls:
                        logger.info(f"Tool call requested: {tool_call.function.name} with args: {tool_call.function.arguments}")
                        result = await self._dispatch_tool(tool_call, event_queue)
                        logger.info(f"Tool execution result: {result[:200]}...") # truncate for logging
                        
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": result
                        })
                else:
                    msg = choice.content or 'Analysis complete.'
                    logger.info(f"Agent finished analysis. Final output: {msg}")
                    await event_queue.enqueue_event(
                        new_agent_text_message(f"✅ {msg}")
                    )
                    break
            except Exception as e:
                logger.error(f"Error in agent step: {str(e)}", exc_info=True)
                await event_queue.enqueue_event(
                    new_agent_text_message(f"❌ Process Error: {str(e)}")
                )
                break

    async def cancel(self, context: RequestContext) -> None:
        """Handle cancellation of the agent execution."""
        pass

    def _extract_text(self, context: RequestContext) -> str:
        text = ""
        msg = context.message
        try:
            # Use model_dump() for robust pydantic serialization
            msg_dict = msg.model_dump()
            parts = msg_dict.get("parts", [])
            for p in parts:
                if isinstance(p, dict) and p.get("text"):
                    text += p["text"] + "\n"
                elif hasattr(p, "text") and p.text:
                    text += p.text + "\n"
                    
            if not text and msg_dict.get("text"):
                text = msg_dict["text"]
        except Exception:
            text = str(msg)
            
        return text.strip()

    def _get_system_prompt(self) -> str:
        return (
            "You are a versatile data analysis and automation subagent. "
            "Your primary goal is to assist the main agent by processing requests using your available tools. "
            "You have access to a local bash shell ('execute_bash_command') for file operations and "
            "a specialized image/location processing pipeline ('run_site_check_pipeline'). "
            "Analyze the user's instructions carefully. If they request filtering, data extraction, "
            "and/or site analysis, use the appropriate tools to fulfill the request. "
            "You can find expert guidance for various domains in the 'a2a_agent/skills/' directory. "
            "Use 'execute_bash_command' to list and read these skill files if you believe they will help you "
            "refine your approach to the current task. "
            "After completing all tool calls, provide a concise, professional summary of your actions, "
            "the results obtained, and the status of any generated files."
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
            await event_queue.enqueue_event(new_agent_text_message(f"🚀 Starting audit of {num_sites} locations..."))
            
            try:
                async with sse_client(settings.mcp_server_url) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        
                        # Use a progress handler to relay progress to the A2A event queue
                        async def handle_progress(*args, **kwargs):
                            progress = args[0] if len(args) > 0 else kwargs.get("progress", 0)
                            total = args[1] if len(args) > 1 else kwargs.get("total", None)
                            if progress is not None:
                                percent = (progress / total * 100) if total else progress
                                await event_queue.enqueue_event(
                                    new_agent_text_message(f"⏳ Progress: {percent:.1f}% ({int(progress)}/{int(total) if total else '?'})")
                                )

                        result = await session.call_tool(
                            "process_locations_batch", 
                            args,
                            progress_callback=handle_progress
                        )
                        return result.content[0].text
            except Exception as e:
                import traceback
                error_details = traceback.format_exc()
                logger.error(f"MCP Network Error Detailed:\n{error_details}")
                return f"MCP Network Error: {str(e)}"
        
        return f"Unknown tool: {name}"
