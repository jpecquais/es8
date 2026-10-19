# Image de la ligne de commande es8ctl. Construire depuis la racine du dépôt :
#   docker build -f packages/cli/Dockerfile -t es8-cli .
# MIDI : sous Linux (Raspberry Pi compris), passer la carte son ALSA :
#   docker run --rm --device /dev/snd -v "$PWD:/work" es8-cli read -p <port>
# Sous macOS et Windows, Docker n'a pas accès au MIDI : l'image sert alors aux
# opérations sans pédale (transform, apply en simulation, patches, .bel…).
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends libasound2 \
    && rm -rf /var/lib/apt/lists/*

COPY packages /src/packages
COPY web /src/web
COPY site /src/site
RUN pip install --no-cache-dir "/src/packages/core[midi]" /src/packages/cli \
    && rm -rf /src

WORKDIR /work
ENTRYPOINT ["es8ctl"]
CMD ["--help"]
