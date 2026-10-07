from fastapi import FastAPI

app = FastAPI(
    title="Emprego Real API",
    description="API oficial da plataforma Emprego Real",
    version="1.0.0"
)


@app.get("/")
def root():
    return {
        "status": "online",
        "message": "Emprego Real API funcionando!"
    }


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }
