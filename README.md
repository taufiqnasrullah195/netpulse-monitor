# NetPulse

Warnet IT monitoring dashboard — live host discovery, real-time status polling, event log, and daily reporting. Built as a portfolio project demonstrating network programming, concurrency, event-driven architecture, and SQLite persistence.

![Python](https://img.shields.io/badge/Python-3.11+-blue)
![Tests](https://img.shields.io/badge/tests-32%20passed-brightgreen)
![License](https://img.shields.io/badge/license-MIT-green)

---

## Features

| Feature | Detail |
|---|---|
| Live subnet scan | Async ICMP ping of a full /24 in ~5 seconds (asyncio, bounded semaphore) |
| ARP MAC detection | Reads OS ARP cache, normalizes MAC format |
| Real-time monitoring | Background thread polls every N seconds; status dots update without restart |
| State machine | UP/DOWN/UNKNOWN per host; transition events logged with timestamp |
| Threshold alerts | Desktop toast notification when host offline > configured threshold |
| SQLite persistence | Full poll history and event log survive restarts |
| CSV / PDF export | Daily uptime report with bar chart (matplotlib + reportlab) |
| Detail drawer | Click any host: MAC, hostname, status, latency, last-seen timestamp |
| Wake-on-LAN | Magic packet via directed subnet broadcast — wake offline hosts from the UI |
| Demo / Live toggle | Switch between dummy data and real network scan |
| Config file | `config.yaml` — subnet, poll interval, alert threshold, mode |

---

## Project Structure

```
NetPulse/
├── app.py            # Main window (tkinter/ttk, single-window layout)
├── monitor.py        # Background polling engine + state machine
├── scanner.py        # Async ICMP ping + ARP + reverse DNS
├── db.py             # SQLite persistence (WAL mode, parameterized queries)
├── reporter.py       # CSV/PDF/chart export (matplotlib, reportlab)
├── alerts.py         # Windows toast notification (graceful degradation)
├── wol.py            # Wake-on-LAN magic packet
├── ui_table.py       # Host table widget (ttk.Treeview, Editorial Light palette)
├── ui_eventlog.py    # Event log panel (tk.Text, reverse-chron)
├── config_loader.py  # config.yaml → typed Config dataclass
├── config.yaml       # Runtime configuration
├── test_scanner.py   # 13 tests: ping parser (EN/DE/Linux locales), scan, ARP, config
├── test_monitor.py   # 12 tests: DB CRUD, state transitions, threshold, MAC preservation
├── test_reporter.py  # 7 tests: CSV columns, PDF magic bytes, PNG chart output
└── run_tests.py      # pytest entry point
```

---

## Requirements

- Python 3.11+
- `matplotlib` — chart rendering
- `reportlab` — PDF export
- `pyyaml` — config loading
- `winrt` (optional) — Windows toast notifications

```bash
pip install matplotlib reportlab pyyaml
```

---

## Usage

```bash
# Edit config.yaml first — set your subnet
python app.py
```

### Configuration (`config.yaml`)

```yaml
network:
  subnet: "192.168.1.0/24"      # subnet to scan
  poll_interval_seconds: 10     # how often to scan
  offline_threshold_seconds: 120 # alert after this many seconds offline
  max_concurrent_pings: 50      # concurrency limit

alerts:
  desktop_notification: true

app:
  mode: demo  # demo (dummy data) | live (real network)
```

---

## Running Tests

```bash
python run_tests.py
# or
pytest test_scanner.py test_monitor.py test_reporter.py -v
```

```
32 passed in 8.63s
```

Test coverage:
- Ping output parser: Windows EN/DE, Linux, macOS timeout, ICMP unreachable trap, decimal latency
- Subnet scanner: alive detection, ARP assignment, sort order, progress callback
- Monitoring engine: UP→DOWN, DOWN→UP, no duplicate events, threshold fires once, resets on recovery, MAC preserved on ARP miss
- Database: record + retrieve, latest per host, uptime %, event log ordering
- Reporter: CSV columns, multi-host, empty, PNG chart bytes, PDF magic bytes

---

## CV / Portfolio Notes

**What this proves:**

- **Network programming** — raw ICMP via subprocess, ARP table parsing, UDP magic packets
- **Concurrency** — asyncio with bounded semaphore; background thread engine with queue-based GUI drain
- **Event-driven architecture** — state machine, event log, threshold alerting
- **Data modeling** — SQLite schema design, WAL mode, parameterized queries, uptime% calculation
- **Desktop GUI** — tkinter/ttk single-window layout, real-time Treeview updates, theming
- **Reporting** — matplotlib chart rendering, reportlab PDF generation, CSV export
- **Testing** — 32 tests, mocked subprocess/DB, locale coverage, state machine verification

---

## License

MIT © 2026 Taufiq Nashrullah
