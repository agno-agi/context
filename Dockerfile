# ===========================================================================
# @context — container image
# ===========================================================================

FROM agnohq/python:3.12

# ---------------------------------------------------------------------------
# System dependencies
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Application code
# ---------------------------------------------------------------------------
WORKDIR /app
ENV PYTHONPATH=/app
COPY requirements.txt ./
# `uv pip sync` is strict: it installs exactly the listed packages and drops
# transitive deps that aren't pinned. Fine for a locked file generated against
# the released agno, but PR #8404 pulls in a different fastmcp version whose
# transitive deps aren't in the lock. `uv pip install` is lenient and pulls
# them in. Revert to `sync` once requirements.txt is regenerated.
RUN uv pip install -r requirements.txt --system
COPY . .

# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
RUN chmod +x /app/scripts/entrypoint.sh
ENTRYPOINT ["/app/scripts/entrypoint.sh"]

# ---------------------------------------------------------------------------
# Default command (overridden by compose for dev)
# ---------------------------------------------------------------------------
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
