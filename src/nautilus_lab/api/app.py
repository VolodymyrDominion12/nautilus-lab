from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import subprocess

app = FastAPI(title="Nautilus Lab API")

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

