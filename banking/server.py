import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel

from banking.agents.multi_agent import create_banking_supervisor_agent
from banking.services.langfuse_service import langfuse_service
from banking.services.postgres_db_service import PostgresDBService
from banking.services.postgres_service import postgres_service
from banking.state.checkpointer import get_checkpointer, get_pool
from banking.state.store import get_session, get_store, set_session
from banking.utils.logger import get_logger

logger = get_logger(__name__)
db_service = PostgresDBService()

_cors_origins_env = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
ALLOWED_ORIGINS = (
    [origin.strip() for origin in _cors_origins_env.split(",") if origin.strip()]
    if _cors_origins_env
    else ["*"]
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up Banking Agent API...")

    try:
        langfuse_service.initialize()
    except Exception as exc:
        logger.error("Failed to initialize Langfuse service: %s", exc)

    checkpointer = get_checkpointer()
    if not checkpointer:
        raise RuntimeError("POSTGRESQL_URL is required. Checkpointer was not initialized.")

    pool = get_pool()
    if not pool:
        raise RuntimeError("PostgreSQL pool was not initialized for checkpointer.")

    await pool.open(wait=True, timeout=30)
    logger.info("PostgreSQL connection pool opened")
    await checkpointer.setup()
    logger.info("Async PostgreSQL checkpointer initialized")

    await db_service.initialize()
    await postgres_service.initialize()
    seed_result = await postgres_service.seed_demo_data(reset=True)
    if seed_result.get("skipped"):
        logger.info("Demo banking seed skipped: data already exists")
    else:
        logger.info("Demo banking data seeded (reset=%s)", seed_result.get("reset"))
    logger.info("Banking services initialized successfully")

    yield

    logger.info("Shutting down Banking Agent API...")
    try:
        langfuse_service.flush()
    except Exception as exc:
        logger.error("Error flushing Langfuse: %s", exc)

    try:
        await db_service.close()
    except Exception as exc:
        logger.error("Error closing database service: %s", exc)

    pool = get_pool()
    if pool:
        try:
            await pool.close()
        except Exception as exc:
            logger.error("Error closing checkpointer pool: %s", exc)


app = FastAPI(
    title="Banking Agent API",
    description="LangChain supervisor banking assistant with account and payments specialists",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "service": "banking-agent"}


ROLE_TO_TYPE = {"user": "human", "assistant": "ai", "system": "system", "tool": "tool"}


def _to_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return " ".join(parts)
    return str(content)


def _to_lc_message(msg: dict[str, Any]) -> BaseMessage:
    msg_type = msg.get("type") or ROLE_TO_TYPE.get(str(msg.get("role", "")).lower())
    content = _to_text_content(msg.get("content"))
    if msg_type == "human":
        return HumanMessage(content=content)
    if msg_type == "ai":
        return AIMessage(content=content)
    if msg_type == "system":
        return SystemMessage(content=content)
    if msg_type == "tool":
        return ToolMessage(content=content, tool_call_id=msg.get("tool_call_id", ""))
    return HumanMessage(content=content)


def normalize_input(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload or {}
    if "input" in data:
        inner = data["input"]
        if isinstance(inner, str):
            return {"messages": [HumanMessage(content=inner)]}
        if isinstance(inner, dict):
            if "messages" in inner and isinstance(inner["messages"], list):
                return {"messages": [_to_lc_message(m) for m in inner["messages"]]}
            if "content" in inner:
                return {"messages": [_to_lc_message(inner)]}
            return inner
    if "messages" in data and isinstance(data["messages"], list):
        return {"messages": [_to_lc_message(m) for m in data["messages"]]}
    return {"messages": [HumanMessage(content=str(data))]}


def _extract_last_message_from_chain_output(output: Any) -> str:
    if not isinstance(output, dict):
        return ""
    messages = output.get("messages") or []
    if not messages:
        return ""
    last_message = messages[-1]
    content = getattr(last_message, "content", "")
    return _to_text_content(content).strip()


class ChatMessage(BaseModel):
    role: str
    content: list[dict[str, Any]] | str


class ChatInput(BaseModel):
    messages: list[ChatMessage]
    channel: str = "web"


class StreamRequest(BaseModel):
    input: ChatInput
    thread_id: str | None = None


@app.get("/admin/data-summary")
async def data_summary():
    return await postgres_service.get_data_summary()


@app.post("/chat/stream")
async def chat_stream(request: StreamRequest):
    try:
        normalized_input = normalize_input(request.input.model_dump())

        user_message_content = ""
        if normalized_input.get("messages"):
            last_message = normalized_input["messages"][-1]
            if isinstance(last_message, HumanMessage):
                user_message_content = str(last_message.content)

        conversation_id = request.thread_id or f"banking-thread-{uuid.uuid4()}"
        channel = request.input.channel or "web"

        store = get_store()
        session_data = await get_session(store, conversation_id)
        session_data["channel"] = channel
        await set_session(store, conversation_id, session_data)

        if user_message_content:
            logger.info("[user_message] thread_id=%s content=%s", conversation_id, user_message_content)
            await db_service.append_conversation_message(
                conversation_id=conversation_id,
                role="user",
                content=user_message_content,
                agent_name="User",
            )

        config = {"configurable": {"thread_id": conversation_id}}
        langfuse_handler = langfuse_service.get_handler()
        if langfuse_handler:
            config["callbacks"] = [langfuse_handler]

        async def generate_stream():
            assistant_response = ""
            active_tool_calls = 0

            yield f"data: {json.dumps({'thread_id': conversation_id, 'type': 'session', 'timestamp': time.time()})}\n\n"

            try:
                agent = create_banking_supervisor_agent(use_memory_checkpointer=False)
                graph_input = normalized_input

                async for event in agent.astream_events(graph_input, config=config, version="v2"):
                    event_type = event.get("event")
                    event_name = event.get("name", "")
                    event_data = event.get("data", {})

                    if event_type == "on_tool_start":
                        active_tool_calls += 1
                        tool_start_data = {
                            "thread_id": conversation_id,
                            "type": "tool_start",
                            "tool_name": event_name,
                            "tool_arguments": event_data.get("input", {}),
                            "agent": "BankingSupervisor",
                            "timestamp": time.time(),
                        }
                        yield f"data: {json.dumps(tool_start_data)}\n\n"

                    elif event_type == "on_tool_end":
                        active_tool_calls = max(0, active_tool_calls - 1)
                        output = event_data.get("output")
                        tool_output = getattr(output, "content", output) if output is not None else ""
                        if isinstance(tool_output, (dict, list)):
                            tool_response = json.dumps(tool_output)
                        else:
                            tool_response = str(tool_output)
                        tool_end_data = {
                            "thread_id": conversation_id,
                            "type": "tool_end",
                            "tool_name": event_name,
                            "tool_response": tool_response,
                            "agent": "BankingSupervisor",
                            "timestamp": time.time(),
                        }
                        yield f"data: {json.dumps(tool_end_data)}\n\n"

                    elif event_type == "on_chat_model_stream":
                        # Ignore model-token streams emitted while tools are running.
                        # This prevents nested specialist agent tokens from being merged
                        # into the user-facing supervisor response.
                        if active_tool_calls > 0:
                            continue
                        chunk = event_data.get("chunk")
                        if chunk and hasattr(chunk, "content") and chunk.content:
                            text_content = _to_text_content(chunk.content)
                            assistant_response += text_content
                            yield f"data: {json.dumps({'thread_id': conversation_id, 'type': 'token', 'content': text_content, 'timestamp': time.time()})}\n\n"
                    elif event_type == "on_chain_end" and event_name == "BankingSupervisor":
                        if not assistant_response.strip():
                            final_text = _extract_last_message_from_chain_output(event_data.get("output"))
                            if final_text:
                                assistant_response = final_text

                if not assistant_response.strip():
                    assistant_response = "I completed the request, but no final text response was generated."

                logger.info(
                    "[assistant_response] thread_id=%s agent=%s content=%s",
                    conversation_id,
                    "BankingSupervisor",
                    assistant_response,
                )
                await db_service.append_conversation_message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=assistant_response,
                    agent_name="BankingSupervisor",
                )

                yield f"data: {json.dumps({'thread_id': conversation_id, 'type': 'end_of_response', 'content': assistant_response, 'timestamp': time.time()})}\n\n"
            except Exception as exc:
                logger.error("Error in streaming: %s", exc)
                yield f"data: {json.dumps({'thread_id': conversation_id, 'error': str(exc), 'type': type(exc).__name__})}\n\n"

        return StreamingResponse(
            generate_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Content-Type": "text/event-stream; charset=utf-8",
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/web", response_class=HTMLResponse)
def web_interface():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Banking Agent</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --ink: #0f172a;
            --forest: #0f5132;
            --mint: #9fe3bf;
            --gold: #c9a24d;
            --paper: #f6fbf7;
            --panel: #ffffff;
            --muted: #64748b;
            --border: #dfe7e2;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Manrope', sans-serif;
            background: radial-gradient(circle at top left, rgba(201,162,77,0.35), transparent 28%),
                        linear-gradient(145deg, #0b2f24 0%, #114d39 45%, #1f6b4f 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        .chat-container {
            width: 100%;
            max-width: 960px;
            height: 92vh;
            background: var(--panel);
            border-radius: 24px;
            box-shadow: 0 30px 80px rgba(8, 30, 23, 0.3);
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }
        .chat-header {
            background: linear-gradient(135deg, var(--forest), #156247);
            color: white;
            padding: 22px 28px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .header-info { display: flex; align-items: center; gap: 16px; }
        .logo {
            width: 52px; height: 52px; border-radius: 16px;
            background: linear-gradient(145deg, var(--mint), var(--gold));
            color: var(--forest); display: flex; align-items: center; justify-content: center;
            font-weight: 800;
        }
        .chat-messages {
            flex: 1; overflow-y: auto; padding: 28px;
            background: linear-gradient(180deg, var(--paper), #fbfbfb);
        }
        .message { margin-bottom: 18px; display: flex; gap: 12px; }
        .message.user { flex-direction: row-reverse; }
        .message-avatar {
            width: 40px; height: 40px; border-radius: 12px;
            display: flex; align-items: center; justify-content: center;
            font-weight: 700; flex-shrink: 0;
        }
        .message.user .message-avatar { background: #156247; color: white; }
        .message.assistant .message-avatar { background: #e7f6eb; color: #0f5132; }
        .message-content {
            max-width: 74%; padding: 16px 18px; line-height: 1.6;
            border-radius: 18px; white-space: pre-wrap;
            box-shadow: 0 4px 14px rgba(15, 23, 42, 0.08);
        }
        .message.user .message-content { background: #156247; color: white; }
        .message.assistant .message-content { background: white; color: var(--ink); border: 1px solid var(--border); }
        .typing-indicator { display: none; padding: 14px 18px; background: white; border-radius: 16px; width: fit-content; }
        .typing-indicator.active { display: flex; gap: 6px; }
        .typing-dot { width: 8px; height: 8px; background: #156247; border-radius: 50%; animation: typing 1.4s infinite; }
        .typing-dot:nth-child(2) { animation-delay: 0.2s; }
        .typing-dot:nth-child(3) { animation-delay: 0.4s; }
        @keyframes typing { 0%,60%,100%{transform:translateY(0);opacity:0.4} 30%{transform:translateY(-7px);opacity:1} }
        .chat-input-container { padding: 22px 28px; background: white; border-top: 1px solid var(--border); }
        .chat-input-wrapper { display: flex; gap: 14px; }
        #userInput {
            flex: 1; border: 2px solid var(--border); border-radius: 28px;
            padding: 16px 20px; outline: none; font: inherit; background: #f8fcf9;
        }
        #sendButton {
            width: 54px; height: 54px; border: none; border-radius: 50%;
            background: linear-gradient(135deg, #156247, #2d7c5d);
            color: white; cursor: pointer; font-size: 20px;
        }
        .welcome-message { text-align: center; padding: 48px 24px; color: var(--muted); }
        .welcome-icon {
            width: 84px; height: 84px; margin: 0 auto 22px; border-radius: 26px;
            background: linear-gradient(145deg, #156247, #2d7c5d);
            color: white; display: flex; align-items: center; justify-content: center; font-size: 34px;
        }
    </style>
</head>
<body>
    <div class="chat-container">
        <div class="chat-header">
            <div class="header-info">
                <div class="logo">BK</div>
                <div>
                    <h1>Banking Multi-Agent Assistant</h1>
                    <p style="font-size: 13px; opacity: 0.88;">Session: <span id="sessionIdDisplay">-</span></p>
                </div>
            </div>
            <div style="font-size: 13px; opacity: 0.9;">Account and payments support</div>
        </div>
        <div class="chat-messages" id="chatMessages">
            <div class="welcome-message">
                <div class="welcome-icon">SB</div>
                <h2 style="margin-bottom: 10px; color: #0f5132;">Demo Banking Assistant</h2>
                <p>Try: show my balances, list my payees, transfer 500 SAR, or create a bill payment.</p>
            </div>
            <div class="typing-indicator" id="typingIndicator">
                <div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>
            </div>
        </div>
        <div class="chat-input-container">
            <div class="chat-input-wrapper">
                <input type="text" id="userInput" placeholder="Ask about balances, payments, cards, loans..." autocomplete="off"/>
                <button id="sendButton" onclick="sendMessage()">></button>
            </div>
        </div>
    </div>
    <script>
        const chatMessages = document.getElementById('chatMessages');
        const userInput = document.getElementById('userInput');
        const sendButton = document.getElementById('sendButton');
        const typingIndicator = document.getElementById('typingIndicator');
        let threadId = null;
        let isProcessing = false;
        let isChatReady = false;

        function setInputState(enabled, placeholder = null) {
            userInput.disabled = false;
            sendButton.disabled = !enabled || isProcessing;
            if (placeholder !== null) {
                userInput.placeholder = placeholder;
            }
        }

        function addMessage(role, content) {
            const messageDiv = document.createElement('div');
            messageDiv.className = 'message ' + role;
            const avatar = document.createElement('div');
            avatar.className = 'message-avatar';
            avatar.textContent = role === 'user' ? 'U' : 'B';
            const contentDiv = document.createElement('div');
            contentDiv.className = 'message-content';
            contentDiv.textContent = content;
            messageDiv.appendChild(avatar);
            messageDiv.appendChild(contentDiv);
            chatMessages.insertBefore(messageDiv, typingIndicator);
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }

        function showTyping() { typingIndicator.classList.add('active'); }
        function hideTyping() { typingIndicator.classList.remove('active'); }

        async function sendMessage(messageOverride = null, showUserMessage = true) {
            if (!messageOverride && !isChatReady) return;
            const message = (messageOverride ?? userInput.value).trim();
            if (!message || isProcessing) return;
            isProcessing = true;
            setInputState(false);
            if (!messageOverride) {
                userInput.value = '';
            }
            if (showUserMessage) {
                addMessage('user', message);
            }
            showTyping();

            let assistantMessage = '';
            try {
                const response = await fetch('/chat/stream', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        input: {
                            messages: [{ role: 'user', content: message }],
                            channel: 'web'
                        },
                        thread_id: threadId
                    })
                });

                if (!response.ok) throw new Error('HTTP ' + response.status);

                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\\n');
                    buffer = lines.pop() || '';
                    for (const line of lines) {
                        if (!line.startsWith('data: ')) continue;
                        const raw = line.slice(6);
                        if (!raw.trim()) continue;
                        const parsed = JSON.parse(raw);
                        if (parsed.thread_id && !threadId) {
                            threadId = parsed.thread_id;
                            document.getElementById('sessionIdDisplay').textContent = threadId;
                        }
                        if (parsed.type === 'token') {
                            assistantMessage += parsed.content || '';
                        }
                        if (parsed.type === 'end_of_response' && !assistantMessage) {
                            assistantMessage = parsed.content || '';
                        }
                    }
                }

                hideTyping();
                const welcomeMsg = document.querySelector('.welcome-message');
                if (welcomeMsg) welcomeMsg.remove();
                addMessage('assistant', assistantMessage || 'No response received.');
            } catch (error) {
                hideTyping();
                addMessage('assistant', 'Sorry, there was an error connecting to the server.');
            } finally {
                isProcessing = false;
                if (isChatReady) {
                    setInputState(true, "Ask about balances, payments, and cards...");
                    userInput.focus();
                } else {
                    setInputState(false, "Initializing assistant...");
                }
            }
        }

        userInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                if (!isChatReady || isProcessing) return;
                sendMessage();
            }
        });

        async function initializeGreeting() {
            setInputState(false, "Initializing assistant...");
            await sendMessage('hi', false);
            isChatReady = true;
            setInputState(true, "Ask about balances, payments, and cards...");
            userInput.focus();
        }

        window.addEventListener('load', function() {
            initializeGreeting();
        });
    </script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
