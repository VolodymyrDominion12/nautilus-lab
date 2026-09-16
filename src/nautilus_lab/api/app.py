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

@app.post("/api/research")
def run_research(robot: str = "regime", bars: int = 3000):
    # This is a synchronous call for now; in production it should be async or a background task
    # We use synthetic data by default for safety
    try:
        result = subprocess.run(
            [".venv/bin/python", "-m", "nautilus_lab.interfaces.cli", "research", "--robot", robot, "--synthetic", "--bars", str(bars)],
            capture_output=True,
            text=True,
            check=False
        )
        return {
            "status": "success" if result.returncode == 0 else "error",
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

