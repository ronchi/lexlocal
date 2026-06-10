"""LangGraph ReAct agent for multi-step legal reasoning.

Each call to run_agent() creates its own tool closures so concurrent users
on the LAN cannot share or overwrite each other's KB/model state.
"""

import sys
from pathlib import Path
from typing import Generator, Sequence

from langchain_ollama import ChatOllama
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DEFAULT_OLLAMA_BASE, DEFAULT_EMBED_MODEL, LEGAL_SYSTEM_PROMPT

# Human-readable labels shown in the chat bubble during tool execution
_TOOL_STATUS = {
    "search_knowledge_base": "🔍 Searching knowledge bases…",
    "draft_legal_document":  "📝 Drafting document…",
}


def _make_tools(kb_names: list[str], embed_model: str, ollama_base: str):
    """
    Return a fresh set of tool functions whose KB/model settings are
    captured in a closure.  This makes every request fully independent,
    which is required for safe concurrent use.
    """

    @tool
    def search_knowledge_base(query: str) -> str:
        """
        Search the active knowledge bases for content relevant to the query.
        Use this when you need factual support, case details, contract terms,
        or any information likely found in the uploaded documents.
        """
        from rag.retrieval import retrieve
        return retrieve(query, kb_names, embed_model, ollama_base)

    @tool
    def draft_legal_document(document_type: str, instructions: str, context: str = "") -> str:
        """
        Draft a legal document (motion, letter, contract clause, memo, etc.).
        Provide the document_type (e.g. 'demand letter', 'motion to dismiss'),
        specific instructions, and any context already retrieved.
        """
        prompt = f"Draft a {document_type}.\n\nInstructions: {instructions}\n\n"
        if context:
            prompt += f"Relevant context from documents:\n{context}"
        return prompt

    return [search_knowledge_base, draft_legal_document]


def run_agent(
    user_message: str,
    chat_model: str,
    temperature: float,
    kb_names: Sequence[str],
    embed_model: str = DEFAULT_EMBED_MODEL,
    ollama_base: str = DEFAULT_OLLAMA_BASE,
) -> Generator[str, None, None]:
    """
    Run the LangGraph ReAct agent and stream back text fragments.

    Yields status strings (e.g. "🔍 Searching…") during tool calls so the
    UI always shows activity, followed by the final answer tokens as they
    stream from the model.
    """
    llm = ChatOllama(
        model=chat_model,
        temperature=temperature,
        base_url=ollama_base,
        streaming=True,
    )

    tools = _make_tools(list(kb_names), embed_model, ollama_base)
    agent = create_react_agent(llm, tools=tools, prompt=LEGAL_SYSTEM_PROMPT)

    messages = [HumanMessage(content=user_message)]

    current_tool: str | None = None   # track which tool is running
    answer_started = False            # True once we start streaming the final answer

    for chunk, meta in agent.stream(
        {"messages": messages},
        stream_mode="messages",
    ):
        node = meta.get("langgraph_node", "")

        if node == "agent":
            # ── LLM is either calling a tool OR generating the final answer ──
            tool_calls = getattr(chunk, "tool_calls", None)
            if tool_calls:
                # The model decided to call a tool; show the user what's happening
                tool_name = tool_calls[0].get("name", "")
                status = _TOOL_STATUS.get(tool_name, f"⚙ Running {tool_name}…")
                if status != current_tool:
                    current_tool = status
                    yield f"\n\n_{status}_\n\n"
            else:
                # Content tokens — the final answer is streaming
                content = chunk.content if hasattr(chunk, "content") else ""
                if isinstance(content, str) and content:
                    if not answer_started:
                        answer_started = True
                        current_tool = None
                    yield content
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text = part["text"]
                            if text:
                                if not answer_started:
                                    answer_started = True
                                    current_tool = None
                                yield text

        elif node == "tools":
            # A tool just finished; briefly acknowledge before the model resumes
            tool_msg = getattr(chunk, "name", None)
            label = _TOOL_STATUS.get(tool_msg, "⚙ Tool") if tool_msg else "⚙ Tool"
            yield f"\n\n_✓ {label.lstrip('🔍📝⚙ ').rstrip('…')} complete — reasoning…_\n\n"

    if not answer_started:
        yield "\n\n_(No response generated — check that the Ollama model is running and the selected KBs are indexed.)_"
