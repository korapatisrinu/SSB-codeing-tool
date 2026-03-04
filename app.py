from flask import Flask, render_template, request, redirect, session
import sqlite3
import subprocess
import bcrypt
import os

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
    language TEXT,
    verdict TEXT,
    passed INTEGER,
    total INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
# CODE EXECUTION FUNCTION (MULTI LANGUAGE)
# =========================================================

def run_code(language, code, input_data):

    try:

        if language == "python":
            cmd = ["python", "-c", code]

        elif language == "cpp":
            with open("temp.cpp", "w") as f:
                f.write(code)
            subprocess.run(["g++", "temp.cpp", "-o", "temp"], check=True)
            cmd = ["./temp"]

        elif language == "java":
            with open("Main.java", "w") as f:
                f.write(code)
            subprocess.run(["javac", "Main.java"], check=True)
            cmd = ["java", "Main"]

        elif language == "js":
            cmd = ["node", "-e", code]

        else:
            return "", "Unsupported language"

        result = subprocess.run(
            cmd,
            input=input_data,
            capture_output=True,
            text=True,
            timeout=5
        )

        return result.stdout.strip(), result.stderr.strip()

    except subprocess.TimeoutExpired:
        return "", "Time Limit Exceeded"

    except Exception as e:
        return "", str(e)


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

    # Total problems
    c.execute("SELECT COUNT(*) FROM problems")
    total = c.fetchone()[0]

    # Solved problems (distinct accepted)
    c.execute("""
        SELECT COUNT(DISTINCT problem_id)
        FROM submissions
        WHERE username = ?
        AND verdict = 'Accepted'
    """, (session["user"],))

    solved = c.fetchone()[0] or 0

    pending = total - solved
    if pending < 0:
        pending = 0

    performance = int((solved / total) * 100) if total > 0 else 0

    # Get problem list
    c.execute("SELECT id, title FROM problems")
    problems = c.fetchall()

    print("DEBUG -> Total:", total, "Solved:", solved, "Pending:", pending)

    return render_template(
        "dashboard.html",
        problems=problems,
        solved=solved,
        pending=pending,
        performance=performance
    )
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

    return render_template(
        "admin.html",
        users=users,
        problems=problems,
        msg=msg
    )
@app.route("/delete_problem/<int:pid>")
def delete_problem(pid):

    if session.get("role") != "admin":
        return "Access Denied"

    c.execute("DELETE FROM problems WHERE id=?", (pid,))
    c.execute("DELETE FROM testcases WHERE problem_id=?", (pid,))
    c.execute("DELETE FROM submissions WHERE problem_id=?", (pid,))
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
    language = request.form.get("language", "python")

    output, error = run_code(language, code, stdin_data)

    return output or error


# =========================================================
# EXECUTE — SAMPLE TESTS
# =========================================================

@app.route("/execute/<int:pid>", methods=["POST"])
def execute(pid):

    code = request.form["code"]
    language = request.form.get("language", "python")

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

        output, error = run_code(language, code, clean_input)

        if output.strip() == expected.strip():
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
    language = request.form.get("language", "python")

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

        output, error = run_code(language, code, clean_input)

        if output.strip() == expected.strip():
            passed += 1

    verdict = "Accepted" if passed == total else "Wrong Answer"

    c.execute("""
        INSERT INTO submissions(username, problem_id, code, language, verdict, passed, total)
        VALUES(?,?,?,?,?,?,?)
    """, (session["user"], pid, code, language, verdict, passed, total))

    conn.commit()

    c.execute(
        "SELECT id FROM problems WHERE id > ? ORDER BY id ASC LIMIT 1",
        (pid,)
    )
    next_problem = c.fetchone()
    next_id = next_problem[0] if next_problem else "None"

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