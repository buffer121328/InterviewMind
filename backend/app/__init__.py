from pathlib import Path

from dotenv import load_dotenv

# 统一加载仓库根目录 .env，兼容 source .venv/bin/activate 后 python -m app... 这类入口。
load_dotenv(Path(__file__).resolve().parents[2] / ".env")
load_dotenv()
