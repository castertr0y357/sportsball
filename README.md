# ⚾ SportsBall

> **Because running a league shouldn't require a master's degree.**

SportsBall is an open-source, local-first web platform and Progressive Web App (PWA) designed for church and rec sports leagues. It replaces bloated, complicated sports management software with dead-simple, 1-tap operations for volunteer commissioners, team captains, umpires, and spectators.

---

## 🌟 Key Features

* **⚾ Single-Operator Live Console & Walk-Up DJ**:
  - Keep score with 1 tap on any phone, tablet (iPad), or laptop.
  - Automatic batter walk-up song clips playing through the dugout Bluetooth speaker on batter change.
  - Visual base-runner diamond with 1-tap base occupancy toggles.
  - Multi-sport dynamic controls (Softball/Baseball, Basketball, Volleyball, Flag Football, Soccer, Pickleball).

* **⏱️ Modular Sport-Specific Clocks**:
  - Master Period Game Clock (Start / Pause / +1m / -1m / Auto-horn buzzer).
  - Flag Football dual clocks: **25s/40s Play Clock** + **7s QB Rush / Pass Timer** with visual warnings.
  - 30s / 60s Timeout countdown overlay.
  - Completely toggleable so sports like Softball aren't cluttered with unneeded clocks.

* **📱 100% Offline-Resilient PWA**:
  - Offline Service Worker (`sw.js`) caches HTML, styles, and player walk-up audio files locally into device storage.
  - Full local-first scoring queue in `localStorage` when cell service drops at the ballpark.
  - Automatic batch sync back to the server once connection is restored.

* **🎮 "Practice & Training Sandbox" (GameChanger Killer)**:
  - Accessible without login at `/leagues/practice-sandbox/`.
  - Lets volunteers test controls, practice scoring, run clocks, and hear walk-up sounds in dummy games without touching official records.

* **⚡ Volunteer Quick Hub & 1-Tap Automation**:
  - Automatic round-robin schedule generator (single or double round-robin with bye-week balancing).
  - Standings engine calculating W-L-T, win percentage, points for/against, differential, and streaks.
  - 1-tap playoff bracket seeding (#1 vs #4, #2 vs #3) and advancement to championship finals.
  - Game-day attendance check-in (uncheck missing players to auto-skip them in the batting rotation).

* **📢 Unified Notification Broadcast Hub**:
  - Discord webhooks for instant final score cards and rainout alerts.
  - Built-in Gmail SMTP integration with console fallback for local dev.
  - Optional Twilio SMS text alerts for players who never install apps.
  - Direct 1-tap Venmo, CashApp, and PayPal handles for dues without merchant fees.
  - Anti-garbage electronic liability waiver matching signature against verified account names.

* **🧪 In-App Testing Sandbox (Kubernetes-Ready)**:
  - Accessible at `/testing-sandbox/` to 1-click switch between Commissioner, Coach, Umpire, and Player personas without terminal commands.

---

## 🚀 Quick Start (Local Development)

### 1. Prerequisites
- Python 3.11+
- Git

### 2. Setup
```bash
# Clone the repository
git clone https://github.com/castertr0y357/sportsball.git
cd sportsball

# Create virtual environment
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run migrations & seed demo league data
python manage.py migrate
python manage.py seed_demo_data

# Start local dev server
python manage.py runserver
```
Visit `http://localhost:8000/` in your browser.

---

## 🐳 Docker & Kubernetes Deployment

### Docker Compose
Run the entire production-ready stack (with PostgreSQL 16, Gunicorn, Whitenoise, and persistent volumes) with a single command:
```bash
docker compose up --build
```

### Database & Environment Variables
SportsBall automatically connects to a **PostgreSQL** instance whenever `DATABASE_URL` or `POSTGRES_HOST`/`DB_HOST` is supplied, falling back to SQLite for zero-config local development.

| Variable | Description | Default |
| :--- | :--- | :--- |
| `DATABASE_URL` | Standard connection string (e.g., `postgresql://user:pass@host:5432/dbname`) | Optional (takes precedence) |
| `POSTGRES_HOST` / `DB_HOST` | Hostname or K8s Service of your PostgreSQL instance | `""` (defaults to local SQLite if unset) |
| `POSTGRES_DB` / `DB_NAME` | PostgreSQL database name | `sportsball` |
| `POSTGRES_USER` / `DB_USER` | PostgreSQL username | `sportsball` |
| `POSTGRES_PASSWORD` / `DB_PASSWORD` | PostgreSQL password | `""` |
| `POSTGRES_PORT` / `DB_PORT` | PostgreSQL port | `5432` |
| `DJANGO_DEBUG` | Enable debug mode (`True` / `False`) | `False` |
| `DJANGO_SECRET_KEY` | Unique Django secret key | Pre-configured dev fallback |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated allowed hosts | `localhost,127.0.0.1` |
| `DJANGO_SUPERUSER_USERNAME` | Auto-creates admin on K8s container startup | `""` |
| `DJANGO_SUPERUSER_PASSWORD` | Auto-creates admin password on startup | `""` |
| `DJANGO_SUPERUSER_EMAIL` | Admin email address | `admin@sportsball.local` |
| `EMAIL_HOST_USER` | Gmail address for sending emails | `""` (falls back to console) |
| `EMAIL_HOST_PASSWORD` | Google 16-character App Password | `""` |
| `TWILIO_ACCOUNT_SID` | Optional Twilio SID for SMS alerts | `""` |
| `TWILIO_AUTH_TOKEN` | Optional Twilio Auth Token | `""` |
| `TWILIO_FROM_NUMBER` | Optional Twilio phone number | `""` |

---

## 🧪 Default Test Accounts

You can switch between roles with 1 click in the web UI at `/testing-sandbox/`, or log in with:
* **Universal Password**: `sportsball123`
* **Commissioner (Admin)**: `commissioner`
* **Home Coach (Grace)**: `coach_grace`
* **Away Coach (Calvary)**: `coach_calvary`
* **Field Umpire**: `umpire_bob`
* **Rostered Player**: `player_josh`
* **Free Agent**: `free_agent_eli`

---

## 📄 License
This project is licensed under the MIT License.
