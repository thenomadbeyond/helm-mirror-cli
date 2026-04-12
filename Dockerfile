# Multi-stage build for efficiency and smaller image size

# Stage 1: Builder - Builds the standalone Python executable
FROM docker.io/chainguard/wolfi-base AS builder

USER root
RUN apk update && apk add --no-cache \
    build-base \
    binutils \
    glibc \
    libc-bin \
    python3 && \
    python3 -m ensurepip && \
    pip3 install --no-cache --upgrade pip setuptools && \
    rm -rf /var/cache/apk/*

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY src/ src/

RUN pyinstaller --onefile -n helm-mirror src/main.py

# Stage 2: Final image - Contains only the runtime dependencies and the built binary
FROM docker.io/chainguard/wolfi-base

RUN apk update && apk add --no-cache \
    helm \
    yq \
    crane \
    kubectl && \
    rm -rf /var/cache/apk/*

COPY --from=builder /app/dist/helm-mirror /usr/local/bin/helm-mirror

ENTRYPOINT ["/usr/local/bin/helm-mirror"]
CMD ["--help"]
