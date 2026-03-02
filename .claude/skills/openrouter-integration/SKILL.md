---
name: openrouter-integration
description: Integrate OpenRouter API into FastAPI backends and React frontends. Use when building AI chat interfaces, multi-model selectors, or proxying LLM requests through OpenRouter.
---

# OpenRouter Integration Skill

Patterns for integrating OpenRouter API — a unified gateway to multiple LLMs (GPT-4, Claude, Llama, etc.) — into Python/FastAPI backends with React frontends.

## When to Use This Skill

- Building AI chat/dialog interfaces with model selection
- Proxying LLM requests through OpenRouter from a FastAPI backend
- Managing system prompts loaded from files
- Implementing frontend AI modules with localStorage-stored API keys

## Core Concepts

OpenRouter exposes an OpenAI-compatible API at `https://openrouter.ai/api/v1`. The key difference: the `model` parameter accepts OpenRouter model IDs like `openai/gpt-4o`, `anthropic/claude-3-5-sonnet`, `meta-llama/llama-3.3-70b-instruct`.

## Backend Patterns (FastAPI)

### 1. AI Service (`services/ai_service.py`)

```python
import httpx
from pathlib import Path

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "system_prompt.txt"

def load_system_prompt() -> str:
    """Load system prompt from file — allows editing without rebuild."""
    if SYSTEM_PROMPT_PATH.exists():
        return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    return "You are a helpful assistant."

async def chat_completion(
    messages: list[dict],
    model: str,
    api_key: str,
    system_prompt: str | None = None,
) -> dict:
    """Send chat request to OpenRouter."""
    if system_prompt is None:
        system_prompt = load_system_prompt()

    full_messages = [{"role": "system", "content": system_prompt}] + messages

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{OPENROUTER_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:3000",  # required by OpenRouter
            },
            json={
                "model": model,
                "messages": full_messages,
            },
        )
        response.raise_for_status()
        return response.json()

async def list_models(api_key: str) -> list[dict]:
    """Fetch available models from OpenRouter."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{OPENROUTER_BASE}/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        response.raise_for_status()
        data = response.json()
        return data.get("data", [])
```

### 2. Router (`routers/ai_module.py`)

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from services.ai_service import chat_completion, list_models, load_system_prompt

router = APIRouter(prefix="/api/ai", tags=["ai"])

class ChatRequest(BaseModel):
    messages: list[dict]
    model: str
    api_key: str
    system_prompt: str | None = None

class AnalyzeFeedbackRequest(BaseModel):
    feedback_ids: list[int]
    question: str
    model: str
    api_key: str

@router.post("/chat")
async def chat(req: ChatRequest):
    try:
        result = await chat_completion(
            messages=req.messages,
            model=req.model,
            api_key=req.api_key,
            system_prompt=req.system_prompt,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"OpenRouter error: {str(e)}")

@router.get("/models")
async def get_models(api_key: str):
    try:
        models = await list_models(api_key)
        # Return simplified list
        return [{"id": m["id"], "name": m.get("name", m["id"])} for m in models]
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

@router.get("/system-prompt")
async def get_system_prompt():
    return {"content": load_system_prompt()}
```

### 3. Feedback Analysis Endpoint

```python
@router.post("/analyze-feedback")
async def analyze_feedback(req: AnalyzeFeedbackRequest, db: Session = Depends(get_db)):
    """Load selected unsatisfied feedback and send to AI for analysis."""
    surveys = db.query(Survey).filter(
        Survey.id.in_(req.feedback_ids)
    ).all()

    # Build context from surveys
    context_parts = []
    for s in surveys:
        context_parts.append(f"""
Клиент: {s.client.child_name}
Дата: {s.contact_date}
Удовлетворённость: {s.satisfaction}
Комментарий: {s.comment_text}
Жалоба на сотрудника: {s.complaint_employee_text or '-'}
Жалоба на условия: {s.complaint_conditions_text or '-'}
""")

    context = "\n---\n".join(context_parts)
    user_message = f"Контекст обратных связей:\n{context}\n\nВопрос: {req.question}"

    result = await chat_completion(
        messages=[{"role": "user", "content": user_message}],
        model=req.model,
        api_key=req.api_key,
    )
    return result
```

## Frontend Patterns (React)

### 1. AI Module State

```jsx
// pages/AIModule.jsx
const [apiKey, setApiKey] = useState(() => localStorage.getItem("openrouter_key") || "");
const [model, setModel] = useState("openai/gpt-4o-mini");
const [models, setModels] = useState([]);
const [messages, setMessages] = useState([]);
const [systemPrompt, setSystemPrompt] = useState("");
const [loading, setLoading] = useState(false);

// Persist API key to localStorage
const handleApiKeyChange = (key) => {
  setApiKey(key);
  localStorage.setItem("openrouter_key", key);
};

// Load models when API key is entered
useEffect(() => {
  if (apiKey.length > 10) {
    fetch(`/api/ai/models?api_key=${apiKey}`)
      .then(r => r.json())
      .then(setModels)
      .catch(console.error);
  }
}, [apiKey]);
```

### 2. Chat Send Function

```jsx
const sendMessage = async (text) => {
  const userMsg = { role: "user", content: text };
  const newMessages = [...messages, userMsg];
  setMessages(newMessages);
  setLoading(true);

  try {
    const response = await fetch("/api/ai/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        messages: newMessages,
        model,
        api_key: apiKey,
        system_prompt: systemPrompt || undefined,
      }),
    });
    const data = await response.json();
    const assistantMsg = data.choices[0].message;
    setMessages(prev => [...prev, assistantMsg]);
  } catch (e) {
    console.error("AI error:", e);
  } finally {
    setLoading(false);
  }
};
```

### 3. Load Feedback Context

```jsx
const loadFeedbackContext = async (selectedIds) => {
  // Export unsatisfied feedback as markdown
  const response = await fetch(`/api/export/unsatisfied?format=text`);
  const text = await response.text();
  setMessages([{
    role: "user",
    content: `Загружен контекст неудовлетворённых обратных связей:\n\n${text}`
  }]);
};
```

## Key Rules

1. **Never hardcode API keys** — store in env vars (backend) or localStorage (frontend)
2. **Always set `HTTP-Referer`** in OpenRouter requests — required to identify your app
3. **Use `httpx.AsyncClient`** for async HTTP in FastAPI, not `requests`
4. **System prompt from file** — load via `Path.read_text()`, allows hot updates
5. **Model ID format** — `provider/model-name` (e.g., `openai/gpt-4o`, `anthropic/claude-3-5-sonnet`)
6. **Handle 402/429** — OpenRouter returns 402 for insufficient credits, 429 for rate limits
7. **Timeout** — always set timeout on httpx client (AI responses can be slow)

## Popular Model IDs

| Model | OpenRouter ID |
|-------|--------------|
| GPT-4o | `openai/gpt-4o` |
| GPT-4o mini | `openai/gpt-4o-mini` |
| Claude 3.5 Sonnet | `anthropic/claude-3-5-sonnet` |
| Llama 3.3 70B | `meta-llama/llama-3.3-70b-instruct` |
| Gemini Flash | `google/gemini-flash-1.5` |

## Dependencies

```
httpx>=0.27.0  (backend)
```
