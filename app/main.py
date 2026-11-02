from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import AsyncOpenAI
from mcp import Client
import os
from pathlib import Path
from dotenv import load_dotenv
import json
from system_prompts import system_prompt1

load_dotenv(Path(__file__).resolve().parent / ".env")

DEEPSEEK_KEY = os.getenv("DEEPSEEK_KEY")
if not DEEPSEEK_KEY:
    raise RuntimeError("DEEPSEEK_KEY is not configured")

app = FastAPI()
client = AsyncOpenAI(api_key=DEEPSEEK_KEY, base_url="https://api.deepseek.com")
allowed_tools_names={
    "vkusvill_products_search",
    "vkusvill_product_analogs",
    "vkusvill_product_details",
    "vkusvill_product_barcode",
    "vkusvill_products_discount",
    "vkusvill_recipes",
}

class Request(BaseModel):
    message: str
    context: list = []

class Response(BaseModel):
    message: str
    context: list = []

def get_tools(allowed_names, listed):
    tools = [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.input_schema,
            },
        }
        for tool in listed.tools if tool.name in allowed_names
    ]

    if not tools:
        raise HTTPException(status_code=502, detail="Tools not found")

    return tools

async def call_llm(messages, tools, mcp):
    MAX_TOOL_CALLS = 8

    for _ in range(MAX_TOOL_CALLS):
        response = await client.chat.completions.create(model="deepseek-chat",
                                                        temperature=0.7,
                                                        messages=messages,
                                                        tools=tools,
                                                        tool_choice="auto"
                                                        )

        message = response.choices[0].message
        tool_calls = message.tool_calls or []
        messages.append(message.model_dump(exclude_none=True))

        if not tool_calls:
            return {"message": message.content or "", "context": messages}

        for call in tool_calls:
            tool_name = call.function.name

            if tool_name not in allowed_tools_names:
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": f"Error: tool '{tool_name}' is not available.",
                })
                continue

            arguments = json.loads(call.function.arguments)
            tool_result = await mcp.call_tool(tool_name, arguments)
            result_text = "\n".join(
                item.text for item in tool_result.content if hasattr(item, "text")
            )

            if tool_result.is_error:
                result_text = f"tool execution error: {tool_result.content}"

            messages.append({"role": "tool",
                             "tool_call_id": call.id,
                             "content": result_text})
    raise HTTPException(status_code=502, detail="Model reached the tool-call limit")


@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/request")
async def request(payload: Request) -> Response:
    messages = payload.context + [{"role": "user", "content": payload.message}] if payload.context else [
        {"role": "system", "content": system_prompt1},
        {"role": "user", "content": payload.message},
    ]
    
    if messages[0]["role"] != "system":
        messages.insert(0, {"role": "system", "content": system_prompt1})

    async with Client("https://mcp.vkusvill.ru/mcp") as mcp:
        listed = await mcp.list_tools()
        tools = get_tools(allowed_tools_names, listed)
        result = await call_llm(messages, tools, mcp)

        return {
                "message": result["message"],
                "context": result["context"],
        }