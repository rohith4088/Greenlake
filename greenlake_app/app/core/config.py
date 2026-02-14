import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "GreenLake Dashboard"
    GLP_CLIENT_ID: str = os.getenv("GLP_CLIENT_ID", "")
    GLP_CLIENT_SECRET: str = os.getenv("GLP_CLIENT_SECRET", "")
    GLP_ACCESS_TOKEN: str = os.getenv("GLP_ACCESS_TOKEN", "")
    GLP_COOKIE: str = os.getenv("GLP_COOKIE", "")
    
    # Path to token file if using parsing from file
    TOKEN_FILE: str = os.getenv("TOKEN_FILE", "token.yaml")

    class Config:
        env_file = ".env"

settings = Settings()
