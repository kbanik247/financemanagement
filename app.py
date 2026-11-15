import os, csv, io, sqlite3, secrets, hashlib, json
from datetime import datetime, date, timedelta
from functools import wraps
from flask import Flask, g, request, redirect, url_for, session, flash, render_template, jsonify, send_file, make_response
from werkzeug.security import generate_password_hash, check_password_hash

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(APP_DIR, "finance.db"))
SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-before-deployment-" + secrets.token_hex(16))
CURRENCY = os.environ.get("CURRENCY", "INR")
app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
                  PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
                  MAX_CONTENT_LENGTH=8 * 1024 * 1024)

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS accounts (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 bank_name TEXT NOT NULL, nickname TEXT NOT NULL, account_type TEXT NOT NULL DEFAULT 'Savings',
 opening_balance REAL NOT NULL DEFAULT 0, masked_number TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'Active',
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS categories (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 kind TEXT NOT NULL CHECK(kind IN ('income','expense')), name TEXT NOT NULL, parent TEXT DEFAULT '',
 UNIQUE(user_id,kind,name)
);
CREATE TABLE IF NOT EXISTS properties (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 name TEXT NOT NULL, address TEXT DEFAULT '', monthly_rent REAL DEFAULT 0, active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS transactions (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 account_id INTEGER REFERENCES accounts(id), txn_date TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('income','expense','transfer_in','transfer_out','investment_buy','investment_sell','adjustment')),
 category TEXT DEFAULT '', subcategory TEXT DEFAULT '', source TEXT DEFAULT '',
 property_id INTEGER REFERENCES properties(id), description TEXT NOT NULL,
 amount REAL NOT NULL CHECK(amount > 0), payment_method TEXT DEFAULT '',
 merchant TEXT DEFAULT '', remarks TEXT DEFAULT '', transfer_group TEXT DEFAULT '',
 status TEXT NOT NULL DEFAULT 'posted' CHECK(status IN ('posted','pending')),
 fingerprint TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_txn_user_date ON transactions(user_id,txn_date);
CREATE INDEX IF NOT EXISTS idx_txn_account ON transactions(account_id);
CREATE TABLE IF NOT EXISTS investments (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 asset_type TEXT NOT NULL CHECK(asset_type IN ('mutual_fund','stock','other')),
 name TEXT NOT NULL, symbol TEXT DEFAULT '', amc TEXT DEFAULT '', scheme_category TEXT DEFAULT '',
 exchange TEXT DEFAULT '', units REAL DEFAULT 0, invested_amount REAL DEFAULT 0,
 current_price REAL DEFAULT 0, current_value REAL DEFAULT 0, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS recurring (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 kind TEXT NOT NULL, category TEXT NOT NULL, description TEXT NOT NULL,
 amount REAL NOT NULL, account_id INTEGER REFERENCES accounts(id),
 day_of_month INTEGER NOT NULL DEFAULT 1, active INTEGER DEFAULT 1, last_generated TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS audit_log (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 entity TEXT NOT NULL, entity_id INTEGER, action TEXT NOT NULL, details TEXT DEFAULT '',
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS imports (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 fingerprint TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(user_id,fingerprint)
);
"""

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_db(exc):
    conn = g.pop("db", None)
    if conn is not None: conn.close()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()

def now(): return datetime.now().isoformat(timespec="seconds")
def audit(entity, entity_id, action, details=""):
    db().execute("INSERT INTO audit_log(user_id,entity,entity_id,action,details,created_at) VALUES(?,?,?,?,?,?)",
                 (session["uid"], entity, entity_id, action, details, now()))

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("uid"): return redirect(url_for("login"))
        session.permanent = True
        return fn(*args, **kwargs)
    return wrapped

@app.before_request
def csrf_guard():
    if request.method == "POST" and request.endpoint not in ("login", "register"):
        token = session.get("csrf")
        if not token or request.form.get("_csrf") != token:
            return "Invalid or expired security token. Refresh and try again.", 400

@app.context_processor
def inject_globals():
    return {"currency": CURRENCY, "csrf": session.get("csrf", "")}

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        if len(username) < 3 or len(password) < 12:
            flash("Use a username of at least 3 characters and a password of at least 12 characters.")
            return render_template("register.html")
        try:
            cur = db().execute("INSERT INTO users(username,password_hash,created_at) VALUES(?,?,?)",
                               (username, generate_password_hash(password), now()))
            db().commit()
            session.clear(); session["uid"] = cur.lastrowid; session["username"] = username
            session["csrf"] = secrets.token_urlsafe(32)
            return redirect(url_for("dashboard"))
        except sqlite3.IntegrityError:
            flash("That username is already registered.")
    return render_template("register.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        row = db().execute("SELECT * FROM users WHERE username=?", (request.form.get("username","").strip(),)).fetchone()
        if row and check_password_hash(row["password_hash"], request.form.get("password","")):
            session.clear(); session["uid"] = row["id"]; session["username"] = row["username"]
            session["csrf"] = secrets.token_urlsafe(32); session.permanent = True
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.")
    return render_template("login.html")

@app.post("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def dashboard():
    period = request.args.get("period", "month")
    today = date.today()
    if period == "year": start = date(today.year,1,1)
    elif period == "fy": start = date(today.year if today.month >= 4 else today.year-1,4,1)
    elif period == "previous":
        first = today.replace(day=1); start = (first-timedelta(days=1)).replace(day=1)
        end = first
        return render_template("dashboard.html", data=summary(start.isoformat(), end.isoformat()),
                               accounts=account_balances(), investments=investment_totals(), period=period)
    else: start = today.replace(day=1)
    return render_template("dashboard.html", data=summary(start.isoformat(), (today+timedelta(days=1)).isoformat()),
                           accounts=account_balances(), investments=investment_totals(), period=period)

def account_balances():
    rows = db().execute("""SELECT a.*,
      a.opening_balance + COALESCE(SUM(CASE WHEN t.kind IN ('income','transfer_in','investment_sell') THEN t.amount
      WHEN t.kind IN ('expense','transfer_out','investment_buy') THEN -t.amount
      WHEN t.kind='adjustment' THEN t.amount ELSE 0 END),0) AS balance
      FROM accounts a LEFT JOIN transactions t ON t.account_id=a.id AND t.status='posted'
      WHERE a.user_id=? GROUP BY a.id ORDER BY a.id DESC""",(session["uid"],)).fetchall()
    return rows

def summary(start, end):
    rows = db().execute("""SELECT
      COALESCE(SUM(CASE WHEN kind='income' THEN amount ELSE 0 END),0) income,
      COALESCE(SUM(CASE WHEN kind='expense' THEN amount ELSE 0 END),0) expenses,
      COALESCE(SUM(CASE WHEN kind='investment_buy' THEN amount ELSE 0 END),0) investment_buys,
      COALESCE(SUM(CASE WHEN kind='investment_sell' THEN amount ELSE 0 END),0) investment_sells
      FROM transactions WHERE user_id=? AND status='posted' AND txn_date>=? AND txn_date<?""",
      (session["uid"],start,end)).fetchone()
    total_bank = sum(float(a["balance"]) for a in account_balances())
    opening = db().execute("SELECT COALESCE(SUM(opening_balance),0) n FROM accounts WHERE user_id=?",(session["uid"],)).fetchone()["n"]
    return {"income":rows["income"],"expenses":rows["expenses"],"savings":rows["income"]-rows["expenses"],
            "savings_pct":((rows["income"]-rows["expenses"])/rows["income"]*100 if rows["income"] else 0),
            "investment_buys":rows["investment_buys"],"investment_sells":rows["investment_sells"],
            "bank":total_bank,"opening":opening}

def investment_totals():
    r = db().execute("SELECT COALESCE(SUM(invested_amount),0) invested, COALESCE(SUM(current_value),0) value FROM investments WHERE user_id=?",
                     (session["uid"],)).fetchone()
    return {"invested":r["invested"],"value":r["value"],"gain":r["value"]-r["invested"]}

@app.route("/accounts", methods=["GET","POST"])
@login_required
def accounts():
    if request.method == "POST":
        db().execute("""INSERT INTO accounts(user_id,bank_name,nickname,account_type,opening_balance,masked_number,status,created_at)
          VALUES(?,?,?,?,?,?,?,?)""",(session["uid"],request.form["bank_name"],request.form["nickname"],
          request.form.get("account_type","Savings"),float(request.form.get("opening_balance",0)),
          request.form.get("masked_number",""),request.form.get("status","Active"),now()))
        db().commit(); audit("account",None,"create",request.form["nickname"]); db().commit()
        flash("Bank account added.")
        return redirect(url_for("accounts"))
    return render_template("accounts.html", accounts=account_balances())

@app.route("/transactions", methods=["GET","POST"])
@login_required
def transactions():
    if request.method == "POST":
        kind=request.form["kind"]; amount=float(request.form["amount"])
        if amount <= 0: flash("Amount must be greater than zero."); return redirect(url_for("transactions"))
        aid=request.form.get("account_id") or None
        if kind in ("income","expense","investment_buy","investment_sell") and not aid:
            flash("Select a bank account."); return redirect(url_for("transactions"))
        desc=request.form.get("description","").strip()
        if not desc: flash("Description is required."); return redirect(url_for("transactions"))
        fingerprint=hashlib.sha256("|".join([request.form["txn_date"],kind,str(aid),desc,str(amount)]).encode()).hexdigest()
        dup=db().execute("SELECT id FROM transactions WHERE user_id=? AND fingerprint=?",(session["uid"],fingerprint)).fetchone()
        if dup: flash("Possible duplicate detected; transaction was not added."); return redirect(url_for("transactions"))
        cur=db().execute("""INSERT INTO transactions(user_id,account_id,txn_date,kind,category,subcategory,source,property_id,
          description,amount,payment_method,merchant,remarks,status,fingerprint,created_at,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (session["uid"],aid,request.form["txn_date"],kind,request.form.get("category",""),
           request.form.get("subcategory",""),request.form.get("source",""),request.form.get("property_id") or None,
           desc,amount,request.form.get("payment_method",""),request.form.get("merchant",""),
           request.form.get("remarks",""),request.form.get("status","posted"),fingerprint,now(),now()))
        audit("transaction",cur.lastrowid,"create",desc); db().commit()
        flash("Transaction saved.")
        return redirect(url_for("transactions"))
    txns=db().execute("""SELECT t.*,a.nickname FROM transactions t LEFT JOIN accounts a ON a.id=t.account_id
      WHERE t.user_id=? ORDER BY txn_date DESC,t.id DESC LIMIT 300""",(session["uid"],)).fetchall()
    return render_template("transactions.html", txns=txns, accounts=account_balances(),
                           properties=db().execute("SELECT * FROM properties WHERE user_id=?",(session["uid"],)).fetchall())

@app.route("/transactions/<int:tid>/edit", methods=["GET","POST"])
@login_required
def edit_transaction(tid):
    t=db().execute("SELECT * FROM transactions WHERE id=? AND user_id=?",(tid,session["uid"])).fetchone()
    if not t: return "Not found",404
    if request.method=="POST":
        amount=float(request.form["amount"])
        if amount<=0: flash("Amount must be positive."); return redirect(url_for("edit_transaction",tid=tid))
        db().execute("""UPDATE transactions SET txn_date=?,account_id=?,kind=?,category=?,description=?,amount=?,
          remarks=?,status=?,updated_at=?,fingerprint='' WHERE id=? AND user_id=?""",
          (request.form["txn_date"],request.form.get("account_id") or None,request.form["kind"],
           request.form.get("category",""),request.form["description"],amount,request.form.get("remarks",""),
           request.form.get("status","posted"),now(),tid,session["uid"]))
        audit("transaction",tid,"edit","Historical transaction updated"); db().commit()
        flash("Transaction updated; balances are recalculated from the ledger.")
        return redirect(url_for("transactions"))
    return render_template("edit_transaction.html",t=t,accounts=account_balances())

@app.post("/transactions/<int:tid>/delete")
@login_required
def delete_transaction(tid):
    t=db().execute("SELECT * FROM transactions WHERE id=? AND user_id=?",(tid,session["uid"])).fetchone()
    if t:
        audit("transaction",tid,"delete",json.dumps(dict(t)))
        db().execute("DELETE FROM transactions WHERE id=? AND user_id=?",(tid,session["uid"]))
        db().commit(); flash("Transaction deleted; balance recalculated.")
    return redirect(url_for("transactions"))

@app.route("/transfer", methods=["GET","POST"])
@login_required
def transfer():
    ac=account_balances()
    if request.method=="POST":
        src=int(request.form["from_account"]); dst=int(request.form["to_account"]); amount=float(request.form["amount"])
        if src==dst or amount<=0: flash("Choose two different accounts and a positive amount."); return redirect(url_for("transfer"))
        ids=[r["id"] for r in ac]
        if src not in ids or dst not in ids: return "Invalid account",400
        group=secrets.token_hex(12); d=request.form["txn_date"]; desc=request.form.get("description","Own-account transfer")
        for aid,kind in [(src,"transfer_out"),(dst,"transfer_in")]:
            db().execute("""INSERT INTO transactions(user_id,account_id,txn_date,kind,description,amount,transfer_group,created_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?)""",(session["uid"],aid,d,kind,desc,amount,group,now(),now()))
        audit("transfer",None,"create",group); db().commit()
        flash("Transfer recorded. It is excluded from income and expenses.")
        return redirect(url_for("accounts"))
    return render_template("transfer.html",accounts=ac)

@app.route("/properties", methods=["GET","POST"])
@login_required
def properties():
    if request.method=="POST":
        db().execute("INSERT INTO properties(user_id,name,address,monthly_rent) VALUES(?,?,?,?)",
          (session["uid"],request.form["name"],request.form.get("address",""),float(request.form.get("monthly_rent",0))))
        db().commit(); flash("Property added.")
    props=db().execute("SELECT * FROM properties WHERE user_id=?",(session["uid"],)).fetchall()
    return render_template("properties.html",properties=props)

@app.route("/investments", methods=["GET","POST"])
@login_required
def investments():
    if request.method=="POST":
        typ=request.form["asset_type"]
        invested=float(request.form.get("invested_amount",0)); value=float(request.form.get("current_value",0))
        db().execute("""INSERT INTO investments(user_id,asset_type,name,symbol,amc,scheme_category,exchange,units,
          invested_amount,current_price,current_value,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
          (session["uid"],typ,request.form["name"],request.form.get("symbol",""),request.form.get("amc",""),
           request.form.get("scheme_category",""),request.form.get("exchange",""),float(request.form.get("units",0)),
           invested,float(request.form.get("current_price",0)),value,now()))
        db().commit(); flash("Investment holding saved. Update market value manually.")
        return redirect(url_for("investments"))
    holdings=db().execute("SELECT * FROM investments WHERE user_id=? ORDER BY asset_type,name",(session["uid"],)).fetchall()
    return render_template("investments.html",holdings=holdings,totals=investment_totals())

@app.route("/reports")
@login_required
def reports():
    start=request.args.get("start",date.today().replace(day=1).isoformat())
    end=request.args.get("end",(date.today()+timedelta(days=1)).isoformat())
    s=summary(start,end)
    cats=db().execute("""SELECT category, SUM(amount) amount FROM transactions WHERE user_id=? AND kind='expense'
      AND status='posted' AND txn_date>=? AND txn_date<? GROUP BY category ORDER BY amount DESC""",
      (session["uid"],start,end)).fetchall()
    return render_template("reports.html",s=s,cats=cats,start=start,end=end,accounts=account_balances())

@app.route("/export.csv")
@login_required
def export_csv():
    out=io.StringIO(); w=csv.writer(out)
    w.writerow(["date","type","category","description","amount","account","status","remarks"])
    rows=db().execute("""SELECT t.*,a.nickname FROM transactions t LEFT JOIN accounts a ON a.id=t.account_id
      WHERE t.user_id=? ORDER BY txn_date,id""",(session["uid"],)).fetchall()
    for r in rows: w.writerow([r["txn_date"],r["kind"],r["category"],r["description"],r["amount"],r["nickname"],r["status"],r["remarks"]])
    resp=make_response(out.getvalue()); resp.headers["Content-Type"]="text/csv"
    resp.headers["Content-Disposition"]="attachment; filename=finance_transactions.csv"
    return resp

@app.route("/import", methods=["GET","POST"])
@login_required
def import_csv():
    if request.method=="POST":
        f=request.files.get("file")
        if not f: flash("Choose a CSV file."); return redirect(url_for("import_csv"))
        reader=csv.DictReader(io.StringIO(f.stream.read().decode("utf-8-sig")))
        added=skipped=0
        for row in reader:
            try:
                d=row.get("date") or row.get("txn_date")
                kind=row.get("type") or row.get("kind")
                amount=float(row.get("amount",""))
                desc=row.get("description") or row.get("narration") or "Imported transaction"
                if kind not in ("income","expense") or amount<=0: skipped+=1; continue
                fp=hashlib.sha256("|".join([d,kind,desc,str(amount)]).encode()).hexdigest()
                if db().execute("SELECT id FROM transactions WHERE user_id=? AND fingerprint=?",(session["uid"],fp)).fetchone():
                    skipped+=1; continue
                account=db().execute("SELECT id FROM accounts WHERE user_id=? ORDER BY id LIMIT 1",(session["uid"],)).fetchone()
                if not account: skipped+=1; continue
                db().execute("""INSERT INTO transactions(user_id,account_id,txn_date,kind,category,description,amount,
                  fingerprint,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                  (session["uid"],account["id"],d,kind,row.get("category",""),desc,amount,fp,now(),now()))
                added+=1
            except Exception: skipped+=1
        db().commit(); flash(f"Import complete: {added} added, {skipped} skipped.")
        return redirect(url_for("transactions"))
    return render_template("import.html")

@app.route("/backup")
@login_required
def backup():
    # SQLite online backup API creates a consistent copy.
    target=sqlite3.connect(":memory:")
    db().backup(target)
    buf=io.BytesIO()
    target_path=os.path.join(APP_DIR,"finance_backup_tmp.db")
    target.close()
    src=sqlite3.connect(DB_PATH); dest=sqlite3.connect(target_path)
    src.backup(dest); dest.close(); src.close()
    return send_file(target_path,as_attachment=True,download_name="finance_backup.db")

@app.route("/health")
def health(): return jsonify({"status":"ok"})

if __name__ == "__main__":
    init_db()
    app.run(host=os.environ.get("HOST","127.0.0.1"),port=int(os.environ.get("PORT","5000")),debug=False)
