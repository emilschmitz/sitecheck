import pathlib
import json
import uvicorn
from a2a.server.apps.jsonrpc.fastapi_app import A2AFastAPIApplication
from a2a.server.request_handlers.default_request_handler import DefaultRequestHandler
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.types import AgentCard

from a2a_agent.agent import SiteCheckAgentExecutor


import logging

def create_app():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Load A2A Metadata
    card_path = pathlib.Path(__file__).parent / "agent_card.json"
    with open(card_path, "r") as f:
        card_data = json.load(f)
    
    # Inject dynamic fields
    card_data["url"] = "http://localhost:8000"
    
    agent_card = AgentCard(**card_data)

    # Setup Executor & Handlers
    executor = SiteCheckAgentExecutor()
    handler = DefaultRequestHandler(
        agent_executor=executor, 
        task_store=InMemoryTaskStore()
    )

    # Build FastAPI App
    a2a_app = A2AFastAPIApplication(agent_card=agent_card, http_handler=handler)
    return a2a_app.build()

app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
