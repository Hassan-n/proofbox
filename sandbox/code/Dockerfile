# Bill Lens `code` sandbox profile (contract C4).
# Limits are enforced by the worker at `docker run`, not here:
#   --network none --read-only --cap-drop=ALL --security-opt no-new-privileges
#   --memory=512m --cpus=0.5 --pids-limit=64 --tmpfs /tmp:size=64m
#   -v <job inputs>:/inputs:ro -v <job out>:/out   (20 s wall-clock timeout)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin runner

COPY --chown=root:root --chmod=0555 parse_bill.py /app/parse_bill.py
COPY --chown=root:root --chmod=0555 parse_document.py /app/parse_document.py

USER 10001:10001
WORKDIR /home/runner
# The worker supplies the command, e.g.
#   python /app/parse_bill.py /inputs/bill.pdf --out /out/parse.json
CMD ["python", "/app/parse_bill.py", "--help"]
