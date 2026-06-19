FROM ubuntu:24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    build-essential \
    curl \
    git \
    jq \
    less \
    nano \
    python3 \
    python3-pip \
    wget \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 agent

RUN mkdir -p /workspace && chown agent:agent /workspace

WORKDIR /workspace
USER agent

CMD ["sleep", "infinity"]
