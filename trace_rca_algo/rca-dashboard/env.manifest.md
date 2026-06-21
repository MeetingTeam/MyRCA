# Environment Variables Manifest

## Frontend (rca-dashboard)

| Variable | Required | Description |
|----------|----------|-------------|
| `VITE_GOOGLE_CLIENT_ID` | Yes | Google OAuth2 Client ID (e.g., `xxx.apps.googleusercontent.com`) |
| `VITE_API_URL` | No | API base URL (default: empty = same origin) |

### Development (.env.development)
```
VITE_GOOGLE_CLIENT_ID=<your-google-client-id>
VITE_API_URL=http://localhost:8082
```

### Production (Docker build args)
```bash
docker build \
  --build-arg VITE_GOOGLE_CLIENT_ID=<your-google-client-id> \
  --build-arg VITE_API_URL=/api \
  -t <image>
```

## Backend (trace_rca_service)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GOOGLE_CLIENT_ID` | Yes | - | Google OAuth2 Client ID |
| `JWT_SECRET` | **Yes** | - | JWT signing secret (32+ bytes). **Service fails to start if not set.** |
| `JWT_ALGORITHM` | No | HS256 | JWT algorithm |
| `JWT_EXPIRE_HOURS` | No | 24 | Token expiration in hours |
| `CORS_ORIGINS` | No | * | Comma-separated allowed origins (e.g., `http://localhost:5173,http://34.226.226.116.nip.io:30880`) |
| `CLICKHOUSE_HOST` | No | clickhouse-cluster-client... | ClickHouse host |
| `CLICKHOUSE_PORT` | No | 9000 | ClickHouse port |
| `CLICKHOUSE_USER` | No | default | ClickHouse user |
| `CLICKHOUSE_PASSWORD` | No | (empty) | ClickHouse password |
| `CLICKHOUSE_DATABASE` | No | default | ClickHouse database |

### K8s Secrets (auth-secrets.yaml)
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: rca-auth-secrets
type: Opaque
stringData:
  GOOGLE_CLIENT_ID: "<your-google-client-id>"
  JWT_SECRET: "<random-32-byte-string>"  # Generate: openssl rand -base64 32
  CORS_ORIGINS: "http://34.226.226.116.nip.io:30880"  # Restrict in production
```
