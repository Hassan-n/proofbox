FROM mcr.microsoft.com/playwright/python:v1.48.0-noble
RUN pip install --no-cache-dir playwright==1.48.0 Pillow==10.4.0
RUN useradd -m -u 1002 runner
WORKDIR /app
COPY snap.py /app/snap.py
RUN mkdir -p /out /quarantine && chown -R runner:runner /app /out /quarantine
USER runner
ENTRYPOINT ["python", "/app/snap.py"]