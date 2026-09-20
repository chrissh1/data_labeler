"""Copy the existing assets to Vercel's CDN directory during deployment."""

import shutil
from pathlib import Path


def build_assets(project_dir):
    public_dir = project_dir / "public"
    shutil.copytree(project_dir / "static", public_dir / "static", dirs_exist_ok=True)
    shutil.copy2(project_dir / "tokens.css", public_dir / "tokens.css")


if __name__ == "__main__":
    build_assets(Path(__file__).resolve().parents[1])
