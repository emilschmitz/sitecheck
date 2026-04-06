import json
import asyncio
import uuid
import os
import shutil
from pathlib import Path
from datetime import datetime
from typing import Any, Optional
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.utils import new_agent_text_message
from a2a.types import TaskStatusUpdateEvent, TaskStatus, TaskState, Message, Role, Part, TextPart
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageToolCall, ChatCompletionMessage
from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall

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
            
            # Sanitize status: remove backticks and newlines for clean rendering
            display_status = self._current_status.replace("`", "").replace("\n", " ").replace("\r", "")
            
            # Dynamic truncation: 80% of terminal width
            term_width = shutil.get_terminal_size(fallback=(80, 24)).columns
            limit = int(term_width * 0.8)
            if len(display_status) > limit:
                display_status = display_status[:limit-3] + "..."
            
            msg = f"\r{spinner} {display_status}"
            
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
        if new_status != self._current_status:
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
            # Clear both lines and return cursor
            clear_msg = "\r\033[K\n\033[K\033[F"
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
        # Initialize client with prompt caching headers for Arcee and Anthropic models
        # This is supported by OpenRouter.
        self.client = AsyncOpenAI(
            base_url=str(settings.llm_base_url),
            api_key=settings.llm_api_key.get_secret_value(),
            default_headers={
                "X-Arcee-Cache-Control": "true",
                "anthropic-beta": "prompt-caching-2024-07-31"
            }
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
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_dir = f"/app/output/{timestamp}"
        artifacts_dir = f"{session_dir}/preprocessing-artifacts"
        logs_dir = f"{session_dir}/logs"
        Path(artifacts_dir).mkdir(parents=True, exist_ok=True)
        Path(logs_dir).mkdir(parents=True, exist_ok=True)
        
        # Session-specific logging
        session_log_file = Path(logs_dir) / "session.log"
        file_handler = logging.FileHandler(session_log_file)
        file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
        logger.addHandler(file_handler)

        try:
            context_text = self._extract_text(context)
            
            # Fetch tools dynamically
            local_tools = self._get_local_tools()
            mcp_tools = await self._get_mcp_tools()
            available_tools = local_tools + mcp_tools
            
            # Optional check: usually only full execution environments have task context
            if hasattr(context, "task") and context.task:
                await event_queue.enqueue_event(context.task)

            async with AnimatedStatus(event_queue, "Agent Online. Analyzing context...", cancel_event, task_id, context_id) as status:
                messages = [
                    {"role": "system", "content": self._get_system_prompt(artifacts_dir)},
                    {"role": "user", "content": f"Context: {context_text}"},
                ]
                
                logger.info(f"Agent starting task. Session: {session_dir}")
                
                trace_file = Path(logs_dir) / "agent_llm_traces.jsonl"

                # Multi-step tool loop
                for step in range(settings.max_steps):
                    if cancel_event.is_set():
                        break

                    try:
                        await status.update_progress(None) # Clear any previous progress bars

                        # Log Trace: Request
                        if settings.enable_traces:
                            with open(trace_file, "a") as f:
                                serializable_messages = [
                                    m.model_dump() if hasattr(m, "model_dump") else m 
                                    for m in messages
                                ]
                                f.write(json.dumps({
                                    "step": step,
                                    "timestamp": datetime.now().isoformat(),
                                    "type": "request",
                                    "model": self.model,
                                    "messages": serializable_messages
                                }) + "\n")

                        # Start streaming completion
                        stream = await self.client.chat.completions.create(
                            model=self.model,
                            messages=messages,  # type: ignore
                            tools=available_tools, # type: ignore
                            stream=True
                        )

                        full_content = ""
                        tool_calls_map = {}
                        
                        async for chunk in stream:
                            if cancel_event.is_set():
                                break
                            
                            delta = chunk.choices[0].delta
                            
                            # Accumulate content (Reflection)
                            if delta.content:
                                full_content += delta.content
                                # Update status with the reflection
                                await status.update_status(full_content.strip())
                            
                            # Accumulate tool calls
                            if delta.tool_calls:
                                for tc_delta in delta.tool_calls:
                                    index = tc_delta.index
                                    if index not in tool_calls_map:
                                        tool_calls_map[index] = {
                                            "id": tc_delta.id,
                                            "name": "",
                                            "arguments": ""
                                        }
                                    
                                    if tc_delta.function:
                                        if tc_delta.function.name:
                                            tool_calls_map[index]["name"] += tc_delta.function.name
                                        if tc_delta.function.arguments:
                                            tool_calls_map[index]["arguments"] += tc_delta.function.arguments
                                    
                                    # Update status with current tool being built and argument size
                                    arg_len = len(tool_calls_map[index]['arguments'])
                                    size_str = f" ({arg_len/1024:.1f}KB)" if arg_len > 100 else ""
                                    await status.update_status(f"Preparing {tool_calls_map[index]['name']}{size_str}...")

                        if cancel_event.is_set():
                            break

                        # Log Trace: Response
                        if settings.enable_traces:
                            with open(trace_file, "a") as f:
                                f.write(json.dumps({
                                    "step": step,
                                    "timestamp": datetime.now().isoformat(),
                                    "type": "response",
                                    "content": full_content,
                                    "tool_calls": list(tool_calls_map.values())
                                }) + "\n")

                        # Convert mapped tool calls back to objects for the message history
                        final_tool_calls = []
                        for index in sorted(tool_calls_map.keys()):
                            tc = tool_calls_map[index]
                            final_tool_calls.append(ChatCompletionMessageToolCall(
                                id=tc["id"],
                                type="function",
                                function={"name": tc["name"], "arguments": tc["arguments"]}
                            ))

                        # Create the assistant message for history
                        assistant_msg = ChatCompletionMessage(
                            role="assistant",
                            content=full_content or None,
                            tool_calls=final_tool_calls or None
                        )
                        messages.append(assistant_msg) # type: ignore

                        if final_tool_calls:
                            for tool_call in final_tool_calls:
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
                            msg = full_content or 'Analysis complete.'
                            # Post-process message to strip internal paths
                            clean_msg = msg.replace("/app/output/", "output/").replace("/app/", "")
                            
                            logger.info(f"Agent finished analysis. Final output: {clean_msg}")
                            if not cancel_event.is_set():
                                await event_queue.enqueue_event(
                                    new_agent_text_message(f"✅ {clean_msg}")
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
            logger.removeHandler(file_handler)
            file_handler.close()

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
            "You are a specialized A2A Agent. Your goal is to EXHAUSTIVELY fulfill the user's request without asking for permission to proceed.\n"
            f"WORKSPACE: Your session-specific artifacts directory is `{artifacts_dir}`. Use it for ALL intermediate files, filtered datasets, and logs. `data/` is READ-ONLY. NEVER write files directly to `output/`; always use the provided artifacts directory for your internal files.\n"
            "OPERATIONAL DIRECTIVES:\n"
            "1. NO PERMISSION REQUIRED: If a task is requested and you have the tools/data, DO IT. Do not ask 'Would you like me to proceed?'.\n"
            "2. DATA DISCOVERY: Always check the `data/` directory and the user context for input files (CSV, JSON, txt). Use `ls data/` or `find` to discover available datasets if not explicitly provided.\n"
            "3. READ SKILLS FIRST: Always begin by reading the relevant skill file (e.g., in `a2a_agent/a2a_agent/skills/`) to understand your specific execution mandates.\n"
            "4. ZERO TRUNCATION: Process ALL data points. If there are 1000 records, you must handle them all. The `sitecheck_mcp` tool is optimized for high-volume parallel processing; for small lists (under 20), you can pass a direct list of `addresses`. For long lists (20+), you MUST use the `source_file` and `address_column` arguments to let the tool process the file directly. This is significantly faster and avoids prompt size limits.\n"
            "5. EFFICIENCY & ENCODING: NEVER `cat` large files (1MB+). Use `grep`, `head`, `awk`, or `cut` to extract only the needed lines/columns. For complex CSV filtering, joining, or analysis, you can use `duckdb` (SQL) or `pandas` (via python) which are pre-installed in your environment. \n"
            "   - CRITICAL: If a tool fails with a 'UnicodeDecodeError' or 'binary file' error, the file likely uses `latin-1` encoding. \n"
            "   - FIX: In Pandas, use `pd.read_csv(..., encoding='latin-1')`. In DuckDB, it handles most encodings automatically but you can specify if needed. \n"
            "   - AVOID: Do not use complex `awk` commands for CSV filtering as they often fail on quoted fields and missing headers.\n"
            "   - PYTHON PATH: Always use the absolute path `/app/.venv/bin/python` to run python scripts.\n"
            "6. PATH REPORTING (CRITICAL):\n"
            "   - INTERNAL ROOT: `/app/` is your internal root.\n"
            "   - MAPPING: Any path starting with `/app/` MUST be converted to a relative path for the user.\n"
            "   - EXAMPLE: `/app/output/20260406_.../file.xlsx` MUST be reported as `output/20260406_.../file.xlsx`.\n"
            "   - MANDATE: NEVER include `/app/` in your final response to the user. Always strip it.\n"
            "7. REFLECTION: Before executing tools or providing a final answer, provide a very brief (1-sentence) reflection or plan in your message content (ideally max 100 chars). This will be shown to the user as a status update.\n"
            "8. VISION AUDIT PRECISION: When using `sitecheck_mcp` tools, you MUST identify the SPECIFIC target object from the request. Your `analysis_prompt` must explicitly tell the MCP what object to look for and instruct it that if the object is NOT visible, all other analysis fields MUST be set to 'N/A'. Your `analysis_schema` MUST include a field named `[OBJECT_NAME]_visible` with literal options (e.g., 'Yes', 'No', 'Partial') and 2-3 other cursory-glance fields (e.g., 'Structural_Condition', 'Debris_Present' or other, depending on the user request). ALL fields MUST use literals (enums), NOT booleans. Every analysis field MUST include an 'N/A' option. Limit analysis to 2-3 simple questions answerable at a cursory glance from Street View. Max 1 string field for a one-sentence comment. NO numeric scores. Pass a `timeout` argument of 600 (seconds) for all site checks unless explicitly told otherwise.\n"
            "9. SUMMARIZING: YOUR JOB IS TO PREPROCESS THE DATA AND THEN JUST THROW IT INTO THE MCP WITH THE PROPER ARGUMENTS. THRE IS NOT MUCH ELSE TO DO."
        )


    def _get_local_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "execute_bash_command",
                    "description": (
                        "Run any terminal command via bash. Use for file searching, complex parsing, or data preparation. "
                        "AVAILABLE TOOLS: `duckdb` (SQL for CSV/Parquet), `pandas` (via `python -c`), `grep`, `awk`, `jq`, `sed`.\n"
                        "EXAMPLES:\n"
                        "1. SQL Filtering: `duckdb -c \"COPY (SELECT * FROM 'data/file.csv' WHERE state='CA') TO 'output/filtered.csv' (HEADER, DELIMITER ',')\"`\n"
                        "2. SQL Aggregation: `duckdb -c \"SELECT count(*) FROM 'data/file.csv' WHERE state='CA'\"`\n"
                        "3. Pandas Filtering: `python -c \"import pandas as pd; df=pd.read_csv('data/f.csv'); df[df.state=='CA'].to_csv('out.csv')\"`"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string", "description": "The command string to execute."}
                        },
                        "required": ["command"],
                    },
                },
            }
        ]

    async def _get_mcp_tools(self) -> list[dict[str, Any]]:
        mcp_tools = []
        try:
            async with sse_client(str(settings.mcp_server_url)) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools_list = await session.list_tools()
                    for tool in tools_list.tools:
                        # Convert MCP tool to OpenAI function format
                        schema = tool.inputSchema
                        # Remove output_dir from exposed schema as we inject it internally
                        if "properties" in schema and "output_dir" in schema["properties"]:
                            new_props = dict(schema["properties"])
                            del new_props["output_dir"]
                            schema = dict(schema)
                            schema["properties"] = new_props

                        mcp_tools.append({
                            "type": "function",
                            "function": {
                                "name": tool.name,
                                "description": tool.description,
                                "parameters": schema,
                            },
                        })
        except Exception as e:
            logger.error(f"Failed to fetch MCP tools: {e}")
        return mcp_tools

    async def _dispatch_tool(self, tool_call: Any, event_queue: EventQueue, cancel_event: asyncio.Event, status: AnimatedStatus, session_dir: str, artifacts_dir: str) -> str:
        try:
            name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)

            if name == "execute_bash_command":
                await status.update_status(f"Executing Bash: `{args['command']}`")
                return await execute_bash_command(args["command"])

            # Try to dispatch to MCP
            try:
                async with sse_client(str(settings.mcp_server_url)) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        tools_list = await session.list_tools()
                        mcp_tool_names = [t.name for t in tools_list.tools]
                        
                        if name in mcp_tool_names:
                            num_sites = len(args.get("addresses", []))
                            if num_sites > 0:
                                await status.update_status(f"Analyzing {num_sites} sites...")
                            elif "source_file" in args:
                                await status.update_status(f"Analyzing locations in `{args['source_file']}`...")
                            else:
                                await status.update_status(f"Triggering {name}...")
                            
                            # Inject output_dir for MCP
                            args["output_dir"] = session_dir
                            
                            async def handle_notification(notification):
                                if cancel_event.is_set():
                                    return
                                
                                # Handle progress updates
                                if hasattr(notification, 'params') and 'progress' in notification.params:
                                    p = notification.params
                                    progress = p.get('progress', 0)
                                    total = p.get('total', 0)
                                    if total:
                                        percent = (progress / total * 100)
                                        bar_length = 20
                                        filled_length = int(bar_length * progress // total)
                                        bar = "█" * filled_length + "░" * (bar_length - filled_length)
                                        await status.update_progress(f"|{bar}| {percent:.1f}% ({int(progress)}/{int(total)})")
                                
                                # Handle log/info messages from server
                                if hasattr(notification, 'method') and notification.method == "notifications/message":
                                    msg = notification.params.get("message", "")
                                    if msg:
                                        await status.update_status(msg)

                            async def handle_progress(progress, total, *args):
                                if total:
                                    percent = (progress / total * 100)
                                    bar_length = 20
                                    filled_length = int(bar_length * progress // total)
                                    bar = "█" * filled_length + "░" * (bar_length - filled_length)
                                    msg = f"|{bar}| {percent:.1f}% ({int(progress)}/{int(total)})"
                                    if args and args[0]: # If there is a label
                                        msg += f" - {args[0]}"
                                    await status.update_progress(msg)

                            result = await session.call_tool(
                                name, 
                                args,
                                progress_callback=lambda p, t, *rest: asyncio.create_task(handle_progress(p, t, *rest))
                            )
                            
                            if not cancel_event.is_set():
                                tool_result_text = result.content[0].text
                                try:
                                    res_data = json.loads(tool_result_text)
                                    if "files" in res_data:
                                        files = res_data["files"]
                                        excel = files.get("excel", "").replace("/app/", "")
                                        jsonl = files.get("jsonl", "").replace("/app/", "")
                                        msg = f"📍 Tool completed.\nReports ready:\n- Excel: {excel}\n- JSONL: {jsonl}"
                                        await event_queue.enqueue_event(new_agent_text_message(msg))
                                except Exception:
                                    pass
                                return tool_result_text
                            return "Operation cancelled."
            except Exception as e:
                if name != "execute_bash_command":
                    logger.error(f"MCP Dispatch Error: {e}")
                    return f"MCP Dispatch Error: {e}"
            
            return f"Unknown tool: {name}"
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            logger.error(f"Tool Execution Error Detailed:\n{error_details}")
            return f"Tool Execution Error: {str(e)}"
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            logger.error(f"Tool Execution Error Detailed:\n{error_details}")
            return f"Tool Execution Error: {str(e)}"
