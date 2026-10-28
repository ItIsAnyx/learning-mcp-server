from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import AsyncOpenAI
from mcp import Client
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

DEEPSEEK_KEY = os.getenv("DEEPSEEK_KEY")
if not DEEPSEEK_KEY:
    raise RuntimeError("DEEPSEEK_KEY is not configured")

app = FastAPI()
client = AsyncOpenAI(api_key=DEEPSEEK_KEY, base_url="https://api.deepseek.com")
allowed_tools_names={
    "vkusvill_products_search",
    "vkusvill_product_details",
}

class Request(BaseModel):
    message: str

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

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/request")
async def request(request: Request):
    async with Client("https://mcp.vkusvill.ru/mcp") as mcp:
        listed = await mcp.list_tools()

    tools = get_tools(allowed_tools_names, listed)


    messages = [
        {"role": "system", "content": "You are a helpful assistant"},
        {"role": "user", "content": request.message},
    ]
    response = await client.chat.completions.create(model="deepseek-chat",
                                                temperature=0.7,
                                                messages=messages,
                                                tools=tools,
                                                tool_choice="auto"
                                              )
    message = response.choices[0].message
    return {"message": message.content or "",
            "tool_calls": [
                {
                    "id": call.id,
                    "name": call.function.name,
                    "arguments": call.function.arguments,
                }
                for call in (message.tool_calls or [])
            ],
        }