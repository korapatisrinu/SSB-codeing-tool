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

    username = session["user"]

    import sqlite3
    conn = sqlite3.connect("platform.db")
    c = conn.cursor()

    # Get all problems
    c.execute("SELECT id, title FROM problems")
    problems = c.fetchall()

    total_problems = len(problems)

    # Get solved problems from solved table
    c.execute(
        "SELECT problem_id FROM solved WHERE username=?",
        (username,)
    )

    solved_ids = {row[0] for row in c.fetchall()}

    solved = len(solved_ids)

    pending = total_problems - solved

    performance = int((solved / total_problems) * 100) if total_problems > 0 else 0

    conn.close()

    return render_template(
        "dashboard.html",
        problems=problems,
        solved=solved,
        pending=pending,
        performance=performance
    )
# =========================================================
# contest
# =========================================================

@app.route("/contest/<int:cid>")
def contest(cid):

    if "user" not in session:
        return redirect("/")

    conn = sqlite3.connect("platform.db")
    c = conn.cursor()

    # For now just show all problems (basic contest page)
    c.execute("SELECT id, title FROM problems")
    problems = c.fetchall()

    conn.close()

    return render_template("contest.html", problems=problems, cid=cid)
# =========================================================
# Leaderboard
# =========================================================
@app.route("/leaderboard/<int:cid>")
def leaderboard(cid):

    if "user" not in session:
        return redirect("/")

    conn = sqlite3.connect("platform.db")
    c = conn.cursor()

    # ✅ NEW CORRECT QUERY
    c.execute("""
        SELECT u.username, COUNT(DISTINCT s.problem_id) as solved_count
        FROM users u
        LEFT JOIN submissions s
            ON u.username = s.username
            AND s.verdict = 'Accepted'
        GROUP BY u.username
        ORDER BY solved_count DESC
    """)

    rankings = c.fetchall()
    conn.close()

    return render_template("leaderboard.html", rankings=rankings, cid=cid)
# =========================================================
# ADMIN PANEL
# =========================================================
@app.route("/admin", methods=["GET", "POST"])
def admin():

    if session.get("role") != "admin":
        return "Access Denied"

    conn = sqlite3.connect("platform.db")
    c = conn.cursor()

    msg = ""

    # ================= ADD USER =================
    if request.method == "POST" and "new_user" in request.form:

        username = request.form["new_user"]
        password = request.form["new_pass"]
        role = request.form.get("role", "user")

        hashed_pw = bcrypt.hashpw(
            password.encode(),
            bcrypt.gensalt()
        )

        try:
            c.execute(
                "INSERT INTO users(username, password, role) VALUES(?,?,?)",
                (username, hashed_pw, role)
            )
            conn.commit()
            msg = "User added successfully"
        except:
            msg = "Username already exists"

    # ================= ADD PROBLEM =================
    if request.method == "POST" and "title" in request.form:

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

    # ================= FETCH USERS =================
    c.execute("SELECT username, role FROM users")
    users = c.fetchall()

    # ================= FETCH PROBLEMS =================
    c.execute("SELECT * FROM problems")
    problems = c.fetchall()

    # ================= USER STATISTICS =================
    c.execute("""
        SELECT 
            u.username,
            COUNT(DISTINCT CASE WHEN s.verdict='Accepted' THEN s.problem_id END) AS solved,
            COUNT(s.id) AS submissions,
            SUM(CASE WHEN s.verdict='Accepted' THEN 1 ELSE 0 END) AS accepted,
            SUM(CASE WHEN s.verdict='Wrong Answer' THEN 1 ELSE 0 END) AS wrong
        FROM users u
        LEFT JOIN submissions s
        ON u.username = s.username
        GROUP BY u.username
        ORDER BY solved DESC
    """)

    user_stats = c.fetchall()

    conn.close()

    return render_template(
        "admin.html",
        users=users,
        problems=problems,
        user_stats=user_stats,
        msg=msg
    )
# deleting promble
@app.route("/delete_problem/<int:pid>")
def delete_problem(pid):

    if session.get("role") != "admin":
        return "Access Denied"

    conn, c = get_db()

    c.execute("DELETE FROM problems WHERE id=?", (pid,))
    c.execute("DELETE FROM testcases WHERE problem_id=?", (pid,))
    c.execute("DELETE FROM submissions WHERE problem_id=?", (pid,))

    conn.commit()
    conn.close()

    return redirect("/admin")
# deleting user 
@app.route("/delete_user/<username>")
def delete_user(username):

    if session.get("role") != "admin":
        return "Access Denied"

    conn = sqlite3.connect("platform.db")
    c = conn.cursor()

    # Delete user's submissions first
    c.execute("DELETE FROM submissions WHERE username=?", (username,))

    # Then delete user
    c.execute("DELETE FROM users WHERE username=?", (username,))

    conn.commit()
    conn.close()

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
    language = request.form["language"]
    stdin = request.form.get("stdin", "").strip()
    pid = request.form.get("pid")

    if stdin == "" and pid:

        c.execute("""
            SELECT input FROM testcases
            WHERE problem_id=? AND hidden=0
            ORDER BY id ASC
            LIMIT 1
        """, (pid,))

        row = c.fetchone()

        if row:
            stdin = row[0]

    # 🔥 IMPORTANT FIX HERE
    stdin = stdin.replace("\r\n", "\n").strip() + "\n"

    output, error = run_code(language, code, stdin)

    if error:
        return error

    return output
# detering prombles  reset
@app.route("/reset_user/<username>")
def reset_user(username):

    import sqlite3
    conn = sqlite3.connect("platform.db")
    cur = conn.cursor()

    # delete solved problems
    cur.execute(
        "DELETE FROM solved WHERE username=?",
        (username,)
    )

    # delete submission history
    cur.execute(
        "DELETE FROM submissions WHERE username=?",
        (username,)
    )

    conn.commit()
    conn.close()

    return redirect("/admin")
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

    import sqlite3
    conn = sqlite3.connect("platform.db")
    c = conn.cursor()

    code = request.form["code"]
    language = request.form.get("language", "python")

    # Get test cases
    c.execute(
        "SELECT input, output FROM testcases WHERE problem_id=?",
        (pid,)
    )
    tests = c.fetchall()

    passed = 0
    total = len(tests)

    # Run each testcase
    for inp, expected in tests:

        clean_input = inp.replace("\r\n", "\n")

        if not clean_input.endswith("\n"):
            clean_input += "\n"

        output, error = run_code(language, code, clean_input)

        if output.strip() == expected.strip():
            passed += 1

    verdict = "Accepted" if passed == total else "Wrong Answer"

    # Save submission history
    c.execute("""
        INSERT INTO submissions(username, problem_id, code, language, verdict, passed, total)
        VALUES(?,?,?,?,?,?,?)
    """, (
        session["user"],
        pid,
        code,
        language,
        verdict,
        passed,
        total
    ))

    # Save solved problem
    if verdict == "Accepted":

        c.execute("""
            INSERT OR IGNORE INTO solved(username, problem_id)
            VALUES (?,?)
        """, (session["user"], pid))


    conn.commit()

    # Find next problem
    c.execute(
        "SELECT id FROM problems WHERE id > ? ORDER BY id ASC LIMIT 1",
        (pid,)
    )

    next_problem = c.fetchone()
    next_id = next_problem[0] if next_problem else "None"

    conn.close()

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