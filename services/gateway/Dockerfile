# syntax=docker/dockerfile:1
FROM golang:1.27.3-trixie AS build
WORKDIR /src
ENV CGO_ENABLED=0 GOFLAGS=-trimpath GOMAXPROCS=4
COPY go.mod go.sum ./
RUN go mod download
COPY . .
ARG VERSION=0.1.0
ARG COMMIT=unknown
RUN go build -ldflags "-s -w -X main.version=${VERSION} -X main.commit=${COMMIT}" -o /out/gateway ./cmd/gateway \
 && go build -ldflags "-s -w" -o /out/snapshot ./cmd/snapshot \
 && mkdir -p /out/data && chown 1000:1000 /out/data

FROM gcr.io/distroless/static-debian13:nonroot AS runtime
COPY --from=build /out/gateway /out/snapshot /usr/local/bin/
COPY --from=build --chown=1000:1000 /out/data /data
USER 1000:1000
ENV CANDELA_ENV=production \
    CANDELA_DB_PATH=/data/gateway.sqlite \
    CANDELA_SNAPSHOT_PATH=/data/market.sqlite \
    CANDELA_INTERNAL_ADDR=127.0.0.1:8719 \
    PORT=8080
EXPOSE 8080
VOLUME ["/data"]
ENTRYPOINT ["/usr/local/bin/gateway"]
