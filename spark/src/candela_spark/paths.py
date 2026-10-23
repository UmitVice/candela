import os
from pathlib import Path

ROOT = Path(os.environ.get("SPARK_ROOT", Path(__file__).resolve().parents[2]))
CONFIGS = ROOT / "configs"
DATA = Path(os.environ.get("SPARK_DATA_DIR", ROOT / "data"))
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
TOKENIZED = DATA / "tokenized"
EVAL_DATA = DATA / "eval"
RUNS = Path(os.environ.get("SPARK_RUNS_DIR", ROOT / "runs"))
ARTIFACTS = ROOT / "artifacts"
REPORTS = ROOT / "reports"
TOKENIZER_DIR = ROOT / "tokenizer"
# Named so the repository-wide token*.json secret ignore rule does not hide it.
TOKENIZER_FILE = TOKENIZER_DIR / "spark-bpe-32k.json"
TOKENIZER_META = TOKENIZER_DIR / "spark-bpe-32k.meta.json"
STATE = Path(os.environ.get("CANDELA_HOME", Path.home() / ".candela"))
SPARK_STATE = STATE / "spark"
LEASES = STATE / "leases"
LOGS = Path.home() / "Library" / "Logs" / "Candela"
REPO = ROOT.parent
OBSERVATORY = REPO / "apps" / "web" / "public" / "observatory" / "spark"
