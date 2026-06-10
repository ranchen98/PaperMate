from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.api.chat import router as chat_router

app = FastAPI()

app.include_router(chat_router)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}
