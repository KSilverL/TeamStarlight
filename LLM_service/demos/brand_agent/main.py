from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from agent import generate_brand_animation

app = FastAPI(title="Brand Animation Agent")


class GenerateRequest(BaseModel):
    prompt: str


class GenerateResponse(BaseModel):
    html: str


@app.post("/generate", response_model=GenerateResponse)
def generate(request: GenerateRequest):
    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty.")
    html = generate_brand_animation(request.prompt)
    return GenerateResponse(html=html)
