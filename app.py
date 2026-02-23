from flask import Flask, render_template, request, redirect, session
import sqlite3
import subprocess
import bcrypt

app = Flask(__name__)
app.secret_key = "supersecretkey"

# =========================================================
# DATABASE
# =========================================================

conn = sqlite3.connect("platform.db", check_same_thread=False)
c = conn.cursor()

# USERS
c.execute("""
CREATE TABLE IF NOT EXISTS users(
    username TEXT PRIMARY KEY,
    password BLOB,
    role TEXT,
    rating INTEGER DEFAULT 1200
)
""")

# PROBLEMS
c.execute("""
CREATE TABLE IF NOT EXISTS problems(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    description TEXT
)
""")

# TEST CASES
c.execute("""
CREATE TABLE IF NOT EXISTS testcases(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    problem_id INTEGER,
    input TEXT,
    output TEXT,
    hidden INTEGER DEFAULT 0
)
""")

# SUBMISSIONS
c.execute("""
CREATE TABLE IF NOT EXISTS submissions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT,
    problem_id INTEGER,
    code TEXT,
    verdict TEXT,
    passed INTEGER,
    total INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

# CONTESTS
c.execute("""
CREATE TABLE IF NOT EXISTS contests(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    start_time TEXT,
    end_time TEXT
)
""")

# CONTEST PROBLEMS
c.execute("""
CREATE TABLE IF NOT EXISTS contest_problems(
    contest_id INTEGER,
    problem_id INTEGER
)
""")

# SCORES
c.execute("""
CREATE TABLE IF NOT EXISTS scores(
    contest_id INTEGER,
    username TEXT,
    score INTEGER DEFAULT 0
)
""")

conn.commit()

# =========================================================
# DEFAULT ADMIN
# =========================================================

password = bcrypt.hashpw("admin123".encode(), bcrypt.gensalt())

c.execute(
    "INSERT OR IGNORE INTO users(username, password, role) VALUES(?,?,?)",
    ("admin", password, "admin")
)

conn.commit()

# =========================================================
# LOGIN
# =========================================================

@app.route("/", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form["username"]
        password = request.form["password"].encode()

        c.execute("SELECT password, role FROM users WHERE username=?", (username,))
        row = c.fetchone()

        if row and bcrypt.checkpw(password, row[0]):
            session["user"] = username
            session["role"] = row[1]
            return redirect("/dashboard")

        return "Invalid Login"

    return render_template("login.html")

# =========================================================
# DASHBOARD
# =========================================================
@app.route("/dashboard")
def dashboard():

    if "user" not in session:
        return redirect("/")

    # All problems
    c.execute("SELECT id, title FROM problems")
    problems = c.fetchall()

    total = len(problems)

    # Solved problems (unique + only existing)
    c.execute("""
        SELECT COUNT(DISTINCT s.problem_id)
        FROM submissions s
        INNER JOIN problems p
        ON s.problem_id = p.id
        WHERE s.username=? AND s.verdict='Accepted'
    """, (session["user"],))

    solved = c.fetchone()[0] or 0

    pending = max(total - solved, 0)

    performance = int((solved / total) * 100) if total > 0 else 0

    return render_template(
        "dashboard.html",
        problems=problems,
        solved=solved,
        pending=pending,
        performance=performance
    )

# =========================================================
# CONTEST LIST
# =========================================================

@app.route("/contests")
def contests():

    if "user" not in session:
        return redirect("/")

    c.execute("SELECT * FROM contests")
    all_contests = c.fetchall()

    return render_template("contests.html", contests=all_contests)

# =========================================================
# CONTEST PAGE
# =========================================================

@app.route("/contest/<int:cid>")
def contest(cid):

    if "user" not in session:
        return redirect("/")

    c.execute("SELECT * FROM contests WHERE id=?", (cid,))
    contest = c.fetchone()

    if not contest:
        return "Contest Not Found"

    c.execute("""
        SELECT p.id, p.title
        FROM problems p
        JOIN contest_problems cp
        ON p.id = cp.problem_id
        WHERE cp.contest_id=?
    """, (cid,))

    problems = c.fetchall()

    return render_template("contest.html",
                           contest=contest,
                           problems=problems)

# =========================================================
# ADMIN PANEL
# =========================================================

@app.route("/admin", methods=["GET", "POST"])
def admin():

    if session.get("role") != "admin":
        return "Access Denied"

    msg = ""

    # ADD USER
    if "new_user" in request.form:

        hashed_pw = bcrypt.hashpw(
            request.form["new_pass"].encode(),
            bcrypt.gensalt()
        )

        c.execute(
            "INSERT INTO users(username, password, role) VALUES(?,?,?)",
            (request.form["new_user"], hashed_pw, "user")
        )
        conn.commit()
        msg = "User added successfully"

    # ADD PROBLEM
    if "title" in request.form:

        c.execute(
            "INSERT INTO problems(title, description) VALUES(?,?)",
            (request.form["title"], request.form["description"])
        )

        pid = c.lastrowid

        for i in range(1, 6):
            inp = request.form.get(f"input{i}")
            out = request.form.get(f"output{i}")

            if inp and out:
                c.execute(
                    "INSERT INTO testcases(problem_id,input,output) VALUES(?,?,?)",
                    (pid, inp, out)
                )

        conn.commit()
        msg = "Problem added successfully"

    c.execute("SELECT username, role FROM users")
    users = c.fetchall()

    c.execute("SELECT * FROM problems")
    problems = c.fetchall()

    return render_template("admin.html",
                           users=users,
                           problems=problems,
                           msg=msg)

# =========================================================
# DELETE PROBLEM (FULL CLEAN)
# =========================================================

@app.route("/delete_problem/<int:pid>")
def delete_problem(pid):

    if session.get("role") != "admin":
        return "Access Denied"

    c.execute("DELETE FROM problems WHERE id=?", (pid,))
    c.execute("DELETE FROM testcases WHERE problem_id=?", (pid,))
    c.execute("DELETE FROM submissions WHERE problem_id=?", (pid,))
    c.execute("DELETE FROM contest_problems WHERE problem_id=?", (pid,))

    conn.commit()

    return redirect("/admin")

# =========================================================
# PROBLEM PAGE
# =========================================================

@app.route("/problem/<int:pid>")
def problem(pid):

    if "user" not in session:
        return redirect("/")

    c.execute("SELECT * FROM problems WHERE id=?", (pid,))
    problem = c.fetchone()

    if not problem:
        return "Problem not found"

    return render_template("problem.html", problem=problem)

# =========================================================
# RUN — CUSTOM INPUT
# =========================================================

@app.route("/run", methods=["POST"])
def run():

    code = request.form["code"]
    stdin_data = request.form.get("stdin", "")

    result = subprocess.run(
        ["python", "-c", code],
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=3
    )

    return result.stdout or result.stderr

# =========================================================
# EXECUTE — SAMPLE TESTS
# =========================================================
@app.route("/execute/<int:pid>", methods=["POST"])
def execute(pid):

    code = request.form["code"]

    c.execute(
        "SELECT input, output FROM testcases WHERE problem_id=? AND hidden=0",
        (pid,)
    )
    tests = c.fetchall()

    results = ""

    for i, (inp, expected) in enumerate(tests, 1):

        clean_input = inp.replace("\r\n", "\n")
        if not clean_input.endswith("\n"):
            clean_input += "\n"

        result = subprocess.run(
            ["python", "-c", code],
            input=clean_input,
            capture_output=True,
            text=True,
            timeout=5
        )

        output = result.stdout.strip()

        if output == expected.strip():
            results += f"Test Case {i}: ✔ Passed\n"
        else:
            results += (
                f"Test Case {i}: ✖ Failed\n"
                f"Expected: {expected}\n"
                f"Got: {output}\n\n"
            )

    return results

# =========================================================
# SUBMIT — FINAL JUDGE
# =========================================================

@app.route("/submit/<int:pid>", methods=["POST"])
def submit(pid):

    if "user" not in session:
        return "Login required"

    code = request.form["code"]

    # Get test cases
    c.execute(
        "SELECT input, output FROM testcases WHERE problem_id=?",
        (pid,)
    )
    tests = c.fetchall()

    passed = 0
    total = len(tests)

    for inp, expected in tests:

        clean_input = inp.replace("\r\n", "\n")
        if not clean_input.endswith("\n"):
            clean_input += "\n"

        result = subprocess.run(
            ["python", "-c", code],
            input=clean_input,
            capture_output=True,
            text=True,
            timeout=5
        )

        output = result.stdout.strip()

        if output == expected.strip():
            passed += 1

    verdict = "Accepted" if passed == total else "Wrong Answer"

    # Save submission
    c.execute("""
        INSERT INTO submissions(username, problem_id, code, verdict, passed, total)
        VALUES(?,?,?,?,?,?)
    """, (session["user"], pid, code, verdict, passed, total))
    conn.commit()

    # Find next problem
    c.execute(
        "SELECT id FROM problems WHERE id > ? ORDER BY id ASC LIMIT 1",
        (pid,)
    )
    next_problem = c.fetchone()

    next_id = next_problem[0] if next_problem else "None"

    # Return data to JS
    return f"{verdict}|{passed}|{total}|{next_id}"

# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# =========================================================

if __name__ == "__main__":
    app.run(debug=True)