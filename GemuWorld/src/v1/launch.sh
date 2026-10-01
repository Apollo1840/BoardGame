#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

conda_bin="${CONDA_EXE:-}"
if [[ -z "$conda_bin" ]]; then
    conda_bin="$(type -P conda || true)"
fi
if [[ -z "$conda_bin" ]]; then
    for candidate in "$HOME/anaconda3/bin/conda" "$HOME/miniconda3/bin/conda" "$HOME/miniforge3/bin/conda"; do
        if [[ -x "$candidate" ]]; then
            conda_bin="$candidate"
            break
        fi
    done
fi
if [[ -z "$conda_bin" || ! -x "$conda_bin" ]]; then
    echo "Conda was not found. Install Conda or add it to PATH." >&2
    exit 1
fi

exec "$conda_bin" run --no-capture-output -n web python scripts/serve.py "$@"
