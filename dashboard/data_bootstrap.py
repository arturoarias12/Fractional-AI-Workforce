"""Optional download of the team's offline ETF workbooks, for deployments
that can't just place the files in the repo root by hand (e.g. Streamlit
Community Cloud, which deploys straight from the public GitHub repo, where
these two files are intentionally gitignored - see ``.gitignore`` and
``README.md``'s "Supply the offline data" section).

Completely inert unless ETF_HISTORICAL_PRICES_URL / ETF_INFO_URL are set:
local development, which already places these files by hand, is unaffected
either way. Designed to be called once, early, before anything tries to
read the workbooks - safe to call from both the Streamlit process and the
backend script subprocess, since it's a cheap no-op once the files exist.

Recommended source for the URLs: a GitHub Release asset on this repo (Releases
support large binary attachments without bloating the tracked git history the
way committing the xlsx files directly would) - not the public repo's git
history itself, since these files are deliberately excluded from it.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _download(url: str, destination: Path) -> None:
    import requests  # local import: only needed when a download actually happens

    response = requests.get(url, timeout=120, stream=True)
    response.raise_for_status()
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = destination.with_suffix(destination.suffix + ".part")
    with tmp_path.open("wb") as f:
        for chunk in response.iter_content(chunk_size=1 << 20):
            f.write(chunk)
    tmp_path.replace(destination)


def ensure_offline_data_present() -> None:
    """Download the ETF workbooks if missing and download URLs are configured.

    Silently does nothing if the files already exist, or if no URL is
    configured for a missing file - the existing, already-clear error in
    run_full_research_loop_demo.py surfaces normally in that case.
    """

    files = {
        "ETF_HISTORICAL_PRICES_PATH": ("ETF_HISTORICAL_PRICES_URL", "ETF_historical_prices.xlsx"),
        "ETF_INFO_PATH": ("ETF_INFO_URL", "ETF_info.xlsx"),
    }
    for path_env, (url_env, default_name) in files.items():
        destination = Path(os.environ.get(path_env, default_name))
        if not destination.is_absolute():
            destination = REPO_ROOT / destination
        if destination.exists():
            continue
        url = os.environ.get(url_env)
        if not url:
            continue  # not configured - leave the existing clear error path alone
        print(f"Downloading {destination.name} from {url_env}...")
        _download(url, destination)
        print(f"  -> saved to {destination}")


__all__ = ["ensure_offline_data_present"]
