import os
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"


def load_yaml(name: str) -> dict:
    path = CONFIG_DIR / name
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def config_dir() -> Path:
    return CONFIG_DIR


def project_root() -> Path:
    return ROOT
