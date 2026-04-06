import json
import asyncio
import uuid
from typing import Any, Optional
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.utils import new_agent_text_message
from a2a.types import TaskStatusUpdateEvent, TaskStatus, TaskState, Message, Role, Part, TextPart
from openai import AsyncOpenAI

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client

from a2a_agent.settings import Settings
from a2a_agent.tools import execute_bash_command
import logging

settings = Settings()
logger = logging.getLogger(__name__)

class AnimatedStatus:
    """Helper to maintain an animated spinner and optional progress bar."""
    def __init__(self, event_queue: EventQueue, initial_message: str, cancel_event: asyncio.Event, task_id: str, context_id: str):
        self.event_queue = event_queue
        self.cancel_event = cancel_event
        self.task_id = task_id
        self.context_id = context_id
        self.spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self._current_status = initial_message
        self._second_line: Optional[str] = None
        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None

    async def __aenter__(self):
        self._task = asyncio.create_task(self._animate())
        return self

    async def _animate(self):
        i = 0
        while not self._stop_event.is_set() and not self.cancel_event.is_set():
            spinner = self.spinner_chars[i % len(self.spinner_chars)]
            msg = f"\r{spinner} {self._current_status}"
            
            # If we have a progress bar or second line, append it
            if self._second_line:
                msg += f"\n{self._second_line}\033[F"
            
            try:
                # Use TaskStatusUpdateEvent with final=False for intermediate updates.
                # Sending a Message object would cause the EventConsumer to close the queue.
                status_event = TaskStatusUpdateEvent(
                    task_id=self.task_id,
                    context_id=self.context_id,
                    final=False,
                    status=TaskStatus(
                        state=TaskState.working,
                        message=Message(
                            role=Role.agent,
                            parts=[Part(root=TextPart(text=msg))],
                            message_id=str(uuid.uuid4())
                        )
                    )
                )
                await self.event_queue.enqueue_event(status_event)
            except Exception:
                # If queue is closed or pipe is broken, signal cancellation to the agent
                logger.info("Connection lost. Aborting task...")
                self.cancel_event.set()
                break
                
            i += 1
            await asyncio.sleep(0.1)

    async def update_status(self, new_status: str):
        """Update the primary status text (next to the spinner)."""
        self._current_status = new_status
        logger.info(f"STATUS: {new_status}")

    async def update_progress(self, progress_line: Optional[str]):
        """Update the second line (e.g., the progress bar)."""
        self._second_line = progress_line
        if progress_line:
            logger.info(f"PROGRESS: {progress_line}")

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._stop_event.set()
        if self._task:
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        # Final clear of the status area
        try:
            clear_msg = "\r" + " " * 80 + "\n" + " " * 80 + "\033[F\033[F"
            # Using a TaskStatusUpdateEvent here as well to avoid closing the queue prematurely
            # although usually the execution is about to finish anyway.
            status_event = TaskStatusUpdateEvent(
                task_id=self.task_id,
                context_id=self.context_id,
                final=False,
                status=TaskStatus(
                    state=TaskState.working,
                    message=Message(
                        role=Role.agent,
                        parts=[Part(root=TextPart(text=clear_msg))],
                        message_id=str(uuid.uuid4())
                    )
                )
            )
            await self.event_queue.enqueue_event(status_event)
        except Exception:
            pass

class SiteCheckAgentExecutor(AgentExecutor):
    def __init__(self):
        self.client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.openrouter_api_key.get_secret_value(),
        )
        self.model = settings.extraction_model
        # Map request_id to a cancellation event
        self._cancellation_tokens: dict[str, asyncio.Event] = {}

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        request_id = context.message.message_id or "default"
        cancel_event = asyncio.Event()
        self._cancellation_tokens[request_id] = cancel_event
        
        # Ensure we have task_id and context_id for updates
        task_id = context.task_id or "unknown-task"
        context_id = context_id = context.context_id or "unknown-context"

        # Create session-specific output directory
        from datetime import datetime
        import os
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_dir = f"output/{timestamp}"
        artifacts_dir = f"{session_dir}/preprocessing-artifacts"
        os.makedirs(artifacts_dir, exist_ok=True)

        try:
            context_text = self._extract_text(context)
            
            # Optional check: usually only full execution environments have task context
            if hasattr(context, "task") and context.task:
                await event_queue.enqueue_event(context.task)

            async with AnimatedStatus(event_queue, "Agent Online. Analyzing context...", cancel_event, task_id, context_id) as status:
                messages = [
                    {"role": "system", "content": self._get_system_prompt(artifacts_dir)},
                    {"role": "user", "content": f"Context: {context_text}"},
                ]
                
                logger.info(f"Agent starting task. Session: {session_dir}")

                # Multi-step tool loop
                for step in range(settings.max_steps):
                    if cancel_event.is_set():
                        break

                    try:
                        await status.update_status(f"Thinking (Step {step + 1}/{settings.max_steps})...")
                        await status.update_progress(None) # Clear any previous progress bars

                        response = await self.client.chat.completions.create(
                            model=self.model,
                            messages=messages,  # type: ignore
                            tools=self._get_tools(), # type: ignore
                        )
                        choice = response.choices[0].message
                        messages.append(choice) # type: ignore

                        if choice.tool_calls:
                            for tool_call in choice.tool_calls:
                                if cancel_event.is_set():
                                    break
                                
                                tool_name = tool_call.function.name
                                tool_args = tool_call.function.arguments
                                logger.info(f"Step {step+1}: Executing {tool_name} with args: {tool_args}")
                                await status.update_status(f"Executing {tool_name}...")
                                
                                result = await self._dispatch_tool(tool_call, event_queue, cancel_event, status, session_dir, artifacts_dir)
                                logger.info(f"Step {step+1}: Tool {tool_name} returned {len(result)} chars.")
                                
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "content": result
                                })
                        else:
                            msg = choice.content or 'Analysis complete.'
                            logger.info(f"Agent finished analysis. Final output: {msg}")
                            if not cancel_event.is_set():
                                await event_queue.enqueue_event(
                                    new_agent_text_message(f"✅ {msg}")
                                )
                            break
                    except Exception as e:
                        logger.error(f"Error in agent step: {str(e)}", exc_info=True)
                        if not cancel_event.is_set():
                            await event_queue.enqueue_event(
                                new_agent_text_message(f"❌ Process Error: {str(e)}")
                            )
                        break
        finally:
            self._cancellation_tokens.pop(request_id, None)

    async def cancel(self, context: RequestContext) -> None:
        """Handle cancellation of the agent execution."""
        request_id = context.message.message_id or "default"
        if request_id in self._cancellation_tokens:
            logger.info(f"Received cancellation request for: {request_id}")
            self._cancellation_tokens[request_id].set()

    def _extract_text(self, context: RequestContext) -> str:
        text = ""
        msg = context.message
        try:
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

    def _get_system_prompt(self, artifacts_dir: str) -> str:
        return (
            "You are a specialized Real Estate Due Diligence Subagent. "
            f"WORKSPACE: Your session-specific artifacts directory is `{artifacts_dir}`. It has ALREADY been created. Use it for ALL intermediate files, filtered datasets, and logs. `data/` is READ-ONLY.\n"
            "PROCEDURE:\n"
            "1. ALWAYS begin by reading `a2a_agent/a2a_agent/skills/due_diligence.md` to understand your auditing mandates.\n"
            "2. Read/Filter ALL property data from the user context or `data/` files. ZERO TRUNCATION: If there are 50 addresses, you must process all 50.\n"
            "   EFFICIENCY: NEVER `cat` large files (e.g. 1MB+). Use `grep`, `head`, `awk`, or `cut` to extract only the needed lines/columns. Massive context usage will slow you down significantly.\n"
            "3. If property analysis is requested (e.g., due diligence, audit, check), you MUST use the `run_site_check_pipeline` tool with the FULL list of addresses.\n"
            "4. Provide a summary of your findings and explicitly mention the paths to the generated reports (starting with `output/`).\n"
            "STREAMING: Provide a short 'Intent Update' before EVERY tool call starting with '⠋'.\n"
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

    async def _dispatch_tool(self, tool_call: Any, event_queue: EventQueue, cancel_event: asyncio.Event, status: AnimatedStatus, session_dir: str, artifacts_dir: str) -> str:
        name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)

        if name == "execute_bash_command":
            await status.update_status(f"Executing Bash: `{args['command']}`")
            return await execute_bash_command(args["command"])

        if name == "run_site_check_pipeline":
            num_sites = len(args['addresses'])
            await status.update_status(f"Analyzing {num_sites} sites...")
            
            # Inject output_dir for MCP
            args["output_dir"] = session_dir
            
            try:
                async with sse_client(str(settings.mcp_server_url)) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        
                        async def handle_progress(*args, **kwargs):
                            if cancel_event.is_set():
                                return

                            progress = args[0] if len(args) > 0 else kwargs.get("progress", 0)
                            total = args[1] if len(args) > 1 else kwargs.get("total", None)
                            if progress is not None:
                                percent = (progress / total * 100) if total else 0
                                bar_length = 20
                                filled_length = int(bar_length * progress // total) if total else 0
                                bar = "█" * filled_length + "░" * (bar_length - filled_length)
                                
                                await status.update_progress(f"|{bar}| {percent:.1f}% ({int(progress)}/{int(total) if total else '?'})")

                        result = await session.call_tool(
                            "process_locations_batch", 
                            args,
                            progress_callback=handle_progress
                        )
                        
                        if not cancel_event.is_set():
                            return result.content[0].text
                        return "Operation cancelled."
            except Exception as e:
                import traceback
                error_details = traceback.format_exc()
                logger.error(f"MCP Network Error Detailed:\n{error_details}")
                return f"MCP Network Error: {str(e)}"
        
        return f"Unknown tool: {name}"
