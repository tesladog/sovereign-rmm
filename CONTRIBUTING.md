# Contributing to Sovereign RMM

## How to Contribute

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Development Setup

```bash
git clone https://github.com/tesladog/sovereign-rmm.git
cd sovereign-rmm
cp .env.example .env
docker compose up -d
```

## Code Style

- Python: Follow PEP 8
- JavaScript: Use semicolons
- 4 spaces for indentation

## Testing

Test your changes before submitting:
```bash
docker compose build --no-cache
docker compose up -d
curl http://localhost:8000/api/health
```
