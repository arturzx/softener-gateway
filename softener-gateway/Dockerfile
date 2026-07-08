ARG BUILD_FROM=ghcr.io/home-assistant/base:latest

FROM ${BUILD_FROM} AS ui-builder

RUN apk add --no-cache nodejs npm

WORKDIR /build

COPY ui/package.json ui/package-lock.json ./ui/
RUN cd ui && npm ci

COPY ui ./ui
COPY images ./images
RUN cd ui && npm run build

FROM ${BUILD_FROM}

ARG BUILD_ARCH=amd64
ARG BUILD_VERSION=0.1.0

LABEL \
  io.hass.name="Softener Gateway" \
  io.hass.description="Local/bridge gateway for EcoWater/iQua-family softeners, including Viessmann, EcoWater, North Star, Morton, Whirlpool, Rheem, GE and Kenmore branded devices." \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="addon" \
  io.hass.arch="${BUILD_ARCH}"

RUN \
  apk add --no-cache \
    ca-certificates \
    py3-pip \
    py3-virtualenv \
    python3

WORKDIR /app

COPY --from=ui-builder /build/ui/dist/ /opt/softener-gateway-ui/

COPY pyproject.toml ./
COPY src ./src

RUN \
  python3 -m virtualenv /opt/softener-gateway \
  && /opt/softener-gateway/bin/pip install --no-cache-dir --upgrade pip \
  && /opt/softener-gateway/bin/pip install --no-cache-dir .

COPY run.sh /run.sh
RUN chmod a+x /run.sh

ENV \
  PATH="/opt/softener-gateway/bin:${PATH}" \
  SOFTENER_GATEWAY_UI_DIR="/opt/softener-gateway-ui"

CMD ["/run.sh"]
