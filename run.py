import os

import uvicorn

APP_PORT = int(os.getenv("PORT", os.getenv("APP_PORT", "8765")))
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")


if __name__ == "__main__":
    uvicorn.run("app.main:app", host=APP_HOST, port=APP_PORT, reload=False)
