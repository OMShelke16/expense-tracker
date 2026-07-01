import os
import csv
import io
from datetime import datetime, date
from collections import defaultdict
from calendar import month_name

from flask import Flask, render_template, redirect, url_for, request, flash, jsonify, Response, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
db_url = os.environ.get("DATABASE_URL", "sqlite:///expenses.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+pg8000://", 1)
elif db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+pg8000://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message_category = "warning"

CATEGORIES = ["Food","Transport","Housing","Utilities","Entertainment","Health","Shopping","Education","Travel","Insurance","Other"]

# --------------- Models ---------------

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expenses = db.relationship("Expense", backref="user", lazy=True, cascade="all, delete-orphan")
    budgets = db.relationship("Budget", backref="user", lazy=True, cascade="all, delete-orphan")
    savings = db.relationship("Saving", backref="user", lazy=True, cascade="all, delete-orphan")

    def set_password(self, p): self.password_hash = generate_password_hash(p)
    def check_password(self, p): return check_password_hash(self.password_hash, p)


class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(140), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    note = db.Column(db.String(255))
    date = db.Column(db.Date, nullable=False, default=date.today)
    expense_type = db.Column(db.String(20), nullable=False, default="regular")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    @property
    def monthly_equivalent(self):
        return self.amount / 12.0 if self.expense_type == "yearly" else self.amount

    def covers_month(self, year, month):
        if self.expense_type != "yearly":
            return self.date.year == year and self.date.month == month
        start = self.date.year * 12 + (self.date.month - 1)
        target = year * 12 + (month - 1)
        return 0 <= (target - start) < 12


class Budget(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), nullable=False)
    month = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    __table_args__ = (db.UniqueConstraint("user_id","category","month","year", name="uq_budget"),)


class Saving(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), nullable=False)
    month = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    budget_amount = db.Column(db.Float, nullable=False)
    spent_amount = db.Column(db.Float, nullable=False)
    saved_amount = db.Column(db.Float, nullable=False)
    settled_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)


@login_manager.user_loader
def load_user(uid): return User.query.get(int(uid))

# --------------- Helpers ---------------

def get_monthly_spend(user_id, year, month):
    spend = defaultdict(float)
    for e in Expense.query.filter_by(user_id=user_id).all():
        if e.covers_month(year, month):
            spend[e.category] += e.monthly_equivalent
    return spend


def settle_past_months(user_id):
    today = date.today()
    for b in Budget.query.filter_by(user_id=user_id).all():
        past = (b.year < today.year) or (b.year == today.year and b.month < today.month)
        if not past: continue
        exists = Saving.query.filter_by(user_id=user_id, category=b.category, month=b.month, year=b.year).first()
        if exists: continue
        spent = get_monthly_spend(user_id, b.year, b.month).get(b.category, 0.0)
        saved = max(0.0, b.amount - spent)
        db.session.add(Saving(user_id=user_id, category=b.category, month=b.month, year=b.year,
                              budget_amount=b.amount, spent_amount=spent, saved_amount=saved))
    db.session.commit()

# --------------- Auth ---------------

@app.route("/register", methods=["GET","POST"])
def register():
    if current_user.is_authenticated: return redirect(url_for("dashboard"))
    if request.method == "POST":
        u = request.form.get("username","").strip()
        e = request.form.get("email","").strip().lower()
        p = request.form.get("password","")
        c = request.form.get("confirm_password","")
        if not u or not e or not p: flash("All fields required.", "danger")
        elif p != c: flash("Passwords do not match.", "danger")
        elif len(p) < 6: flash("Password must be at least 6 characters.", "danger")
        elif User.query.filter_by(username=u).first(): flash("Username taken.", "danger")
        elif User.query.filter_by(email=e).first(): flash("Email already registered.", "danger")
        else:
            user = User(username=u, email=e)
            user.set_password(p)
            db.session.add(user); db.session.commit()
            flash("Account created! Please log in.", "success")
            return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET","POST"])
def login():
    if current_user.is_authenticated: return redirect(url_for("dashboard"))
    if request.method == "POST":
        u = request.form.get("username","").strip()
        p = request.form.get("password","")
        user = User.query.filter_by(username=u).first()
        if user and user.check_password(p):
            login_user(user)
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user(); flash("Logged out.", "info")
    return redirect(url_for("login"))

# --------------- Dashboard ---------------

@app.route("/")
def index():
    return redirect(url_for("dashboard") if current_user.is_authenticated else url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    settle_past_months(current_user.id)
    expenses = Expense.query.filter_by(user_id=current_user.id).order_by(Expense.date.desc()).all()
    total = sum(e.amount for e in expenses)
    today = date.today()

    this_month_spend = get_monthly_spend(current_user.id, today.year, today.month)
    this_month_total = sum(this_month_spend.values())

    by_category = defaultdict(float)
    for e in expenses: by_category[e.category] += e.amount

    months, monthly_totals = [], []
    for i in range(5, -1, -1):
        m = (today.month - i - 1) % 12 + 1
        y = today.year + ((today.month - i - 1) // 12)
        spend = get_monthly_spend(current_user.id, y, m)
        months.append(date(y, m, 1).strftime("%b %Y"))
        monthly_totals.append(round(sum(spend.values()), 2))

    budgets = Budget.query.filter_by(user_id=current_user.id, year=today.year, month=today.month).all()
    budget_progress = []
    for b in budgets:
        spent = this_month_spend.get(b.category, 0.0)
        pct = min(100, round((spent / b.amount) * 100, 1)) if b.amount > 0 else 0
        budget_progress.append({"category": b.category, "budget": b.amount, "spent": round(spent,2), "pct": pct, "over": spent > b.amount})

    total_savings = db.session.query(db.func.sum(Saving.saved_amount)).filter_by(user_id=current_user.id).scalar() or 0.0
    yearly_count = Expense.query.filter_by(user_id=current_user.id, expense_type="yearly").count()
    yearly_total = db.session.query(db.func.sum(Expense.amount)).filter_by(user_id=current_user.id, expense_type="yearly").scalar() or 0.0

    return render_template("dashboard.html",
        expenses=expenses[:10], total=round(total,2),
        this_month_total=round(this_month_total,2), expense_count=len(expenses),
        categories=list(by_category.keys()), category_totals=[round(v,2) for v in by_category.values()],
        months=months, monthly_totals=monthly_totals, budget_progress=budget_progress,
        total_savings=round(total_savings,2), yearly_count=yearly_count, yearly_total=round(yearly_total,2))

# --------------- Expenses CRUD ---------------

@app.route("/expenses")
@login_required
def expenses_list():
    page = request.args.get("page",1,type=int)
    cat = request.args.get("category","")
    etype = request.args.get("type","")
    q = Expense.query.filter_by(user_id=current_user.id)
    if cat: q = q.filter_by(category=cat)
    if etype: q = q.filter_by(expense_type=etype)
    pagination = q.order_by(Expense.date.desc()).paginate(page=page, per_page=12, error_out=False)
    return render_template("expenses.html", expenses=pagination.items, pagination=pagination,
                           categories=CATEGORIES, active_category=cat, active_type=etype)


def parse_form(form):
    title = form.get("title","").strip()
    note = form.get("note","").strip()
    category = form.get("category","Other")
    expense_type = "yearly" if form.get("is_yearly") else "regular"
    errors = []
    try:
        amount = float(form.get("amount",""))
        if amount <= 0: raise ValueError
    except ValueError:
        errors.append("Enter a valid positive amount."); amount = 0
    if not title: errors.append("Title is required.")
    try:
        parsed_date = datetime.strptime(form.get("date",""), "%Y-%m-%d").date()
    except ValueError:
        parsed_date = date.today()
    return {"title":title,"amount":amount,"category":category,"note":note,"date":parsed_date,"expense_type":expense_type}, errors


@app.route("/expenses/add", methods=["GET","POST"])
@login_required
def add_expense():
    if request.method == "POST":
        data, errors = parse_form(request.form)
        if errors:
            for e in errors: flash(e,"danger")
        else:
            db.session.add(Expense(user_id=current_user.id, **data)); db.session.commit()
            flash("Yearly expense added — amortized monthly for budgets." if data["expense_type"]=="yearly" else "Expense added!","success")
            return redirect(url_for("expenses_list"))
    return render_template("add_expense.html", categories=CATEGORIES, today=date.today().isoformat())


@app.route("/expenses/<int:eid>/edit", methods=["GET","POST"])
@login_required
def edit_expense(eid):
    expense = Expense.query.filter_by(id=eid, user_id=current_user.id).first_or_404()
    if request.method == "POST":
        data, errors = parse_form(request.form)
        if errors:
            for e in errors: flash(e,"danger")
        else:
            for k,v in data.items(): setattr(expense, k, v)
            db.session.commit(); flash("Expense updated!","success")
            return redirect(url_for("expenses_list"))
    return render_template("edit_expense.html", expense=expense, categories=CATEGORIES)


@app.route("/expenses/<int:eid>/delete", methods=["POST"])
@login_required
def delete_expense(eid):
    e = Expense.query.filter_by(id=eid, user_id=current_user.id).first_or_404()
    db.session.delete(e); db.session.commit(); flash("Deleted.","info")
    return redirect(url_for("expenses_list"))

# --------------- Budgets & Savings ---------------

@app.route("/budgets", methods=["GET","POST"])
@login_required
def budgets():
    today = date.today()
    year = request.args.get("year", today.year, type=int)
    month = request.args.get("month", today.month, type=int)

    if request.method == "POST":
        for cat in CATEGORIES:
            val = request.form.get(f"budget_{cat}","").strip()
            if not val: continue
            try: amt = float(val)
            except ValueError: continue
            existing = Budget.query.filter_by(user_id=current_user.id, category=cat, month=month, year=year).first()
            if amt <= 0:
                if existing: db.session.delete(existing)
            elif existing: existing.amount = amt
            else: db.session.add(Budget(user_id=current_user.id, category=cat, month=month, year=year, amount=amt))
        db.session.commit(); flash("Budgets saved!","success")
        return redirect(url_for("budgets", year=year, month=month))

    settle_past_months(current_user.id)
    bmap = {b.category: b.amount for b in Budget.query.filter_by(user_id=current_user.id, year=year, month=month).all()}
    spend = get_monthly_spend(current_user.id, year, month)
    rows = []
    for c in CATEGORIES:
        b = bmap.get(c, 0); s = round(spend.get(c,0.0),2)
        pct = min(100, round((s/b)*100,1)) if b>0 else 0
        rows.append({"category":c,"budget":b,"spent":s,"pct":pct,"over":b>0 and s>b,"remaining":round(b-s,2)})

    total_savings = db.session.query(db.func.sum(Saving.saved_amount)).filter_by(user_id=current_user.id).scalar() or 0.0
    recent_savings = Saving.query.filter_by(user_id=current_user.id).order_by(Saving.year.desc(), Saving.month.desc()).limit(12).all()
    prev_m = 12 if month==1 else month-1; prev_y = year-1 if month==1 else year
    next_m = 1 if month==12 else month+1; next_y = year+1 if month==12 else year
    return render_template("budgets.html", rows=rows, year=year, month=month,
        month_name=month_name[month], total_savings=round(total_savings,2),
        recent_savings=recent_savings,
        prev_month=prev_m, prev_year=prev_y, next_month=next_m, next_year=next_y,
        is_current=(year==today.year and month==today.month))

# --------------- Exports ---------------

@app.route("/export/csv")
@login_required
def export_csv():
    expenses = Expense.query.filter_by(user_id=current_user.id).order_by(Expense.date.desc()).all()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Date","Title","Category","Type","Amount","Note"])
    for e in expenses:
        w.writerow([e.date.isoformat(), e.title, e.category,
                    "Yearly" if e.expense_type=="yearly" else "Regular",
                    f"{e.amount:.2f}", e.note or ""])
    resp = Response(out.getvalue(), mimetype="text/csv")
    resp.headers["Content-Disposition"] = f"attachment; filename=expenses_{date.today().isoformat()}.csv"
    return resp


@app.route("/export/pdf")
@login_required
def export_pdf():
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet

    expenses = Expense.query.filter_by(user_id=current_user.id).order_by(Expense.date.desc()).all()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.6*inch, bottomMargin=0.6*inch)
    styles = getSampleStyleSheet()
    story = []
    story.append(Paragraph(f"Expense Report — {current_user.username}", styles["Title"]))
    story.append(Paragraph(f"Generated: {date.today().strftime('%d %b %Y')}", styles["Normal"]))
    story.append(Spacer(1,12))
    total = sum(e.amount for e in expenses)
    story.append(Paragraph(f"Total: Rs. {total:,.2f}   |   Entries: {len(expenses)}", styles["Heading3"]))
    story.append(Spacer(1,12))
    data = [["Date","Title","Category","Type","Amount (Rs.)"]]
    for e in expenses:
        data.append([e.date.strftime("%d %b %Y"), e.title, e.category,
                     "Yearly" if e.expense_type=="yearly" else "Regular",
                     f"{e.amount:,.2f}"])
    t = Table(data, colWidths=[0.9*inch,2.0*inch,1.1*inch,0.9*inch,1.1*inch], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#6366f1")),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("FONTSIZE",(0,0),(-1,-1),9),
        ("ALIGN",(4,0),(4,-1),"RIGHT"),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f5f6fa")]),
        ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#dddddd")),
        ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
    ]))
    story.append(t)
    doc.build(story)
    buf.seek(0)
    return send_file(buf, mimetype="application/pdf", as_attachment=True,
                     download_name=f"expenses_{date.today().isoformat()}.pdf")


with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True)
