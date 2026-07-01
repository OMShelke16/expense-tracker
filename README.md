# Expense Tracker

A professional, multi-user expense tracker built with Flask, SQLAlchemy, and Bootstrap. Includes login/signup, a dashboard with charts (category breakdown + 6-month trend), and full CRUD for expenses with filtering and pagination.

## Features
- User accounts (signup/login/logout) — each user only sees their own data
- Add, edit, delete expenses with category, amount, date, and notes
- Dashboard with summary cards and Chart.js visualizations
- Category filtering and pagination on the expenses list
- Works with SQLite locally and PostgreSQL in production (auto-detected)

## Project structure
```
expense-tracker/
├── app.py                 # Flask app, models, routes
├── requirements.txt
├── Procfile                # tells Render/Heroku how to run the app
├── templates/               # Jinja2 HTML templates
└── static/css/style.css     # custom styling
```

## Run locally

1. Create a virtual environment and install dependencies:
   ```bash
   python3 -m venv venv
   source venv/bin/activate        # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. Run the app:
   ```bash
   python app.py
   ```

3. Open `http://localhost:5000` in your browser. The SQLite database (`expenses.db`) is created automatically on first run.

## Deploy for free on Render

Render's free web service tier is the simplest way to host this.

1. **Push this project to a GitHub repository.** Create a new repo and push all these files (`app.py`, `requirements.txt`, `Procfile`, `templates/`, `static/`).

2. **Create a free PostgreSQL database on Render** (optional but recommended — SQLite on Render's free tier resets when the instance restarts, so a real database keeps your data):
   - In the Render dashboard: New → PostgreSQL → choose the Free plan → create it.
   - Copy the "Internal Database URL" once it's ready.

3. **Create the web service:**
   - In the Render dashboard: New → Web Service → connect your GitHub repo.
   - Runtime: Python 3
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn app:app`
   - Choose the Free instance type.

4. **Set environment variables** on the web service (Environment tab):
   - `SECRET_KEY` → any long random string (used to sign session cookies)
   - `DATABASE_URL` → paste the Postgres Internal Database URL from step 2 (skip this if you're fine with SQLite, but data may not persist across restarts/deploys on the free tier)

5. **Deploy.** Render will build and start the app automatically. Your live URL will look like `https://your-app-name.onrender.com`.

   Note: free Render web services spin down after periods of inactivity and take ~30–60 seconds to wake up on the next visit — this is normal for the free tier.

### Alternative free hosts
- **PythonAnywhere** (free tier, good for small Flask apps, persistent SQLite storage)
- **Railway** (free trial credits, similar workflow to Render)
- **Fly.io** (free allowance, requires their CLI to deploy)

The app is written to work on any of these without changes — they all support the `DATABASE_URL` environment variable pattern and `gunicorn app:app` start command.

## Notes on "professional" touches already included
- Passwords are hashed (never stored in plain text)
- Per-user data isolation (`user_id` foreign key + queries scoped to `current_user`)
- Form validation and flash messages for errors/success
- Responsive Bootstrap UI with a consistent color theme
- Pagination so the expenses list scales with data
- Environment-based config (no secrets hardcoded) ready for production

## Ideas to extend later
- CSV/PDF export of expenses
- Budgets per category with alerts
- Recurring expenses
- Password reset via email
