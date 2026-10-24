from pathlib import Path

DATA_VERSION = "d0.2"
ML_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = ML_DIR.parent
CONTRACTS_DIR = REPO_ROOT / "contracts"
CONFIGS_DIR = ML_DIR / "configs"
DATA_DIR = ML_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
TRACES_DIR = DATA_DIR / "traces"
MANIFESTS_DIR = ML_DIR / "manifests"
DATACARDS_DIR = ML_DIR / "datacards"
REPORTS_DIR = ML_DIR / "reports"
RUNS_DIR = ML_DIR / "runs"
MODELS_DIR = ML_DIR / "models"
ARTIFACTS_DIR = ML_DIR / "artifacts"
VENDOR_DIR = ML_DIR / "vendor"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
WEB_DIR = REPO_ROOT / "apps" / "web"
WEB_OBSERVATORY_DIR = WEB_DIR / "public" / "observatory"
ML_OBSERVATORY_DIR = ARTIFACTS_DIR / "observatory"
