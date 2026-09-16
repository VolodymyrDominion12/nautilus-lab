from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import subprocess
import os
import glob
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Nautilus Lab API")

reports_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "reports")
if not os.path.exists(reports_dir):
    os.makedirs(reports_dir, exist_ok=True)
app.mount("/static_reports", StaticFiles(directory=reports_dir), name="static_reports")


# Setup CORS for the React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Nautilus Lab API is running"}

@app.get("/api/status")
def get_status():
    # Placeholder for actual bot status
    # In a real scenario, this might read from a state file or DB
    return {
        "active_bots": 0,
        "strategies_available": ["regime", "ema", "pairs"],
        "is_live": False
    }

@app.get("/api/reports")
def get_reports():
    reports_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "reports")
    if not os.path.exists(reports_dir):
        return {"reports": []}
    
    files = glob.glob(os.path.join(reports_dir, "*.html"))
    reports = [{"filename": os.path.basename(f), "path": f, "url": f"/static_reports/{os.path.basename(f)}"} for f in files]
    return {"reports": reports}

from fastapi import BackgroundTasks

def run_research_task(robot: str, bars: int, log_path: str):
    with open(log_path, "w") as f:
        f.write(f"Starting research for {robot} ({bars} bars)...\n")
        f.flush()
        try:
            process = subprocess.Popen(
                [".venv/bin/python", "-m", "nautilus_lab.interfaces.cli", "research", "--robot", robot, "--synthetic", "--bars", str(bars)],
                stdout=f,
                stderr=subprocess.STDOUT,
                text=True
            )
            process.wait()
            f.write(f"\nProcess finished with code {process.returncode}\n")
        except Exception as e:
            f.write(f"\nException occurred: {str(e)}\n")

@app.post("/api/research")
def run_research(background_tasks: BackgroundTasks, robot: str = "regime", bars: int = 3000):
    reports_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "reports")
    os.makedirs(reports_dir, exist_ok=True)
    log_path = os.path.join(reports_dir, "last_run.log")
    
    # Clear old log immediately
    open(log_path, 'w').close()
    
    background_tasks.add_task(run_research_task, robot, bars, log_path)
    return {"status": "started", "message": "Research started in the background."}

@app.get("/api/research/log")
def get_research_log():
    reports_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "reports")
    log_path = os.path.join(reports_dir, "last_run.log")
    if os.path.exists(log_path):
        with open(log_path, "r") as f:
            return {"log": f.read()}
    return {"log": ""}


import dotenv
from pydantic import BaseModel
from typing import Dict

class SettingsUpdate(BaseModel):
    settings: Dict[str, str]

@app.get("/api/settings")
def get_settings():
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), ".env")
    if not os.path.exists(env_path):
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), ".env.example")
    
    config = dotenv.dotenv_values(env_path)
    return {"settings": config}

@app.put("/api/settings")
def update_settings(update: SettingsUpdate):
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), ".env")
    # Make sure .env exists, if not create it
    if not os.path.exists(env_path):
        open(env_path, 'a').close()
    
    for key, value in update.settings.items():
        dotenv.set_key(env_path, key, str(value))
        
    return {"status": "success"}

