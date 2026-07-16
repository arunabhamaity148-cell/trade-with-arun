# INSTALL

## Quickstart

```bash
# 1) clone or unzip
# 2) create venv
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate

# 3) install (editable + dev + ML extras)
pip install -e ".[dev,ml]"

# 4) configure
cp .env.example .env            # edit only if you want; defaults work for paper

# 5) run the test suite
pytest -q

# 6) one paper pass for BTCUSDT
twa paper --symbol BTCUSDT --timeframe 1h
```

## Windows
```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev,ml]"
pytest -q
twa paper --symbol BTCUSDT --timeframe 1h
```

## Linux (Ubuntu/Debian)

```bash
sudo apt update && sudo apt install -y python3-venv build-essential
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,ml]"
pytest -q
```

## Verify installation

After `pip install -e ".[dev,ml]"` finishes:

```bash
twa --version
twa config
pytest -q
```

If all three succeed, the installation is healthy.
