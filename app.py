import os
from cs50 import SQL
from flask import Flask, render_template, request, redirect, session
from flask_session import Session
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

app = Flask(__name__)

# ---------------- Session Config ----------------
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# ---------------- Database ----------------
DB_FILE = "book_exchange.db"
if not os.path.exists(DB_FILE):
    open(DB_FILE, "w").close()

db = SQL(f"sqlite:///{DB_FILE}")

# ---------------- Setup ----------------
def setup():
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            hash TEXT,
            email TEXT
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            description TEXT,
            price REAL,
            semester TEXT,
            image_url TEXT,
            seller_id INTEGER
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            buyer_id INTEGER,
            book_id INTEGER,
            quantity INTEGER,
            total REAL,
            status TEXT DEFAULT 'Requested'
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER,
            user_id INTEGER,
            content TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (book_id) REFERENCES books(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER,
            user_id INTEGER,
            rating INTEGER CHECK (rating >= 1 AND rating <= 5),
            content TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (book_id) REFERENCES books(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # Sample user (username: admin, password: password)
    if not db.execute("SELECT * FROM users"):
        db.execute(
            "INSERT INTO users (username, hash, email) VALUES (?, ?, ?)",
            "admin",
            generate_password_hash("password"),
            "admin@example.com"
        )

    # Sample books
    if not db.execute("SELECT * FROM books"):
        user_id = db.execute("SELECT id FROM users WHERE username = 'admin'")[0]["id"]
        books = [
            ("Engineering Mathematics I", "Good condition", 350, "Semester 1",
             "https://via.placeholder.com/300x200?text=Maths", user_id),
            ("Data Structures & Algorithms", "Slightly highlighted", 450, "Semester 3",
             "https://via.placeholder.com/300x200?text=DSA", user_id),
            ("Digital Electronics", "Almost new", 300, "Semester 2",
             "https://via.placeholder.com/300x200?text=Electronics", user_id)
        ]
        for b in books:
            db.execute("""
                INSERT INTO books (name, description, price, semester, image_url, seller_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, *b)

setup()

# ---------------- Login Required ----------------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated

# ---------------- Routes ----------------
@app.route("/")
@login_required
def index():
    books = db.execute("""
        SELECT books.*, users.username AS seller,
               COALESCE(AVG(reviews.rating), 0) AS avg_rating,
               COUNT(DISTINCT reviews.id) AS review_count
        FROM books
        JOIN users ON books.seller_id = users.id
        LEFT JOIN reviews ON reviews.book_id = books.id
        GROUP BY books.id
    """)
    return render_template("index.html", page="index", books=books)

@app.route("/book/<int:id>")
@login_required
def book(id):
    rows = db.execute("""
        SELECT books.*, users.username AS seller,
               COALESCE(AVG(reviews.rating), 0) AS avg_rating,
               COUNT(DISTINCT reviews.id) AS review_count
        FROM books
        JOIN users ON books.seller_id = users.id
        LEFT JOIN reviews ON reviews.book_id = books.id
        WHERE books.id = ?
        GROUP BY books.id
    """, id)
    if not rows:
        return "Book not found"

    book = rows[0]
    comments = db.execute("""
        SELECT comments.*, users.username AS commenter
        FROM comments
        JOIN users ON comments.user_id = users.id
        WHERE comments.book_id = ?
        ORDER BY comments.created_at DESC
    """, id)
    reviews = db.execute("""
        SELECT reviews.*, users.username AS reviewer
        FROM reviews
        JOIN users ON reviews.user_id = users.id
        WHERE reviews.book_id = ?
        ORDER BY reviews.created_at DESC
    """, id)
    user_review = db.execute(
        "SELECT * FROM reviews WHERE book_id = ? AND user_id = ?",
        id, session["user_id"]
    )
    return render_template("index.html", page="book", book=book, 
                           comments=comments, reviews=reviews,
                           user_review=user_review[0] if user_review else None)

@app.route("/add", methods=["GET", "POST"])
@login_required
def add():
    if request.method == "POST":
        db.execute("""
            INSERT INTO books (name, description, price, semester, image_url, seller_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
        request.form.get("name"),
        request.form.get("description"),
        float(request.form.get("price")),
        request.form.get("semester"),
        request.form.get("image_url"),
        session["user_id"]
        )
        return redirect("/")
    return render_template("index.html", page="add")

@app.route("/request", methods=["POST"])
@login_required
def request_book():
    book_id = int(request.form.get("book_id"))
    qty = int(request.form.get("quantity"))
    book = db.execute("SELECT * FROM books WHERE id = ?", book_id)[0]
    if book["seller_id"] == session["user_id"]:
        return "You cannot request your own book"
    total = book["price"] * qty
    db.execute("""
        INSERT INTO requests (buyer_id, book_id, quantity, total)
        VALUES (?, ?, ?, ?)
    """, session["user_id"], book_id, qty, total)
    return redirect("/requests")

@app.route("/requests")
@login_required
def requests_list():
    reqs = db.execute("""
        SELECT requests.*, books.name
        FROM requests
        JOIN books ON requests.book_id = books.id
        WHERE requests.buyer_id = ?
    """, session["user_id"])
    return render_template("index.html", page="requests", requests=reqs)

@app.route("/track/<int:id>")
@login_required
def track(id):
    rows = db.execute("SELECT * FROM requests WHERE id = ?", id)
    if not rows:
        return "Request not found"
    return render_template("index.html", page="track", req=rows[0])

@app.route("/seller")
@login_required
def seller():
    reqs = db.execute("""
        SELECT requests.*, books.name, users.username AS buyer
        FROM requests
        JOIN books ON requests.book_id = books.id
        JOIN users ON requests.buyer_id = users.id
        WHERE books.seller_id = ?
    """, session["user_id"])
    return render_template("index.html", page="seller", requests=reqs)

@app.route("/complete/<int:id>")
@login_required
def complete(id):
    db.execute("UPDATE requests SET status='Completed' WHERE id = ?", id)
    return redirect("/seller")

@app.route("/remove/<int:book_id>", methods=["POST"])
@login_required
def remove_book(book_id):
    book = db.execute("SELECT * FROM books WHERE id = ?", book_id)
    if not book:
        return "Book not found."
    if book[0]["seller_id"] != session["user_id"]:
        return "You are not authorized to remove this book."
    db.execute("DELETE FROM books WHERE id = ?", book_id)
    return redirect("/")

# ---------------- Comments ----------------
@app.route("/comment", methods=["POST"])
@login_required
def add_comment():
    book_id = int(request.form.get("book_id"))
    content = request.form.get("content", "").strip()
    if not content:
        return redirect(f"/book/{book_id}")
    db.execute(
        "INSERT INTO comments (book_id, user_id, content) VALUES (?, ?, ?)",
        book_id, session["user_id"], content
    )
    return redirect(f"/book/{book_id}")

@app.route("/comment/delete/<int:id>", methods=["POST"])
@login_required
def delete_comment(id):
    comment = db.execute("SELECT * FROM comments WHERE id = ?", id)
    if not comment:
        return "Comment not found"
    if comment[0]["user_id"] != session["user_id"]:
        return "Not authorized"
    book_id = comment[0]["book_id"]
    db.execute("DELETE FROM comments WHERE id = ?", id)
    return redirect(f"/book/{book_id}")

# ---------------- Reviews ----------------
@app.route("/review", methods=["POST"])
@login_required
def add_review():
    book_id = int(request.form.get("book_id"))
    rating = int(request.form.get("rating", 0))
    content = request.form.get("content", "").strip()
    if rating < 1 or rating > 5:
        return redirect(f"/book/{book_id}")
    book = db.execute("SELECT seller_id FROM books WHERE id = ?", book_id)
    if not book:
        return "Book not found"
    if book[0]["seller_id"] == session["user_id"]:
        return "You cannot review your own book"
    existing = db.execute(
        "SELECT id FROM reviews WHERE book_id = ? AND user_id = ?",
        book_id, session["user_id"]
    )
    if existing:
        db.execute(
            "UPDATE reviews SET rating = ?, content = ?, created_at = CURRENT_TIMESTAMP WHERE id = ?",
            rating, content, existing[0]["id"]
        )
    else:
        db.execute(
            "INSERT INTO reviews (book_id, user_id, rating, content) VALUES (?, ?, ?, ?)",
            book_id, session["user_id"], rating, content
        )
    return redirect(f"/book/{book_id}")

@app.route("/review/delete/<int:id>", methods=["POST"])
@login_required
def delete_review(id):
    review = db.execute("SELECT * FROM reviews WHERE id = ?", id)
    if not review:
        return "Review not found"
    if review[0]["user_id"] != session["user_id"]:
        return "Not authorized"
    book_id = review[0]["book_id"]
    db.execute("DELETE FROM reviews WHERE id = ?", id)
    return redirect(f"/book/{book_id}")

# ---------------- Auth ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    session.clear()
    if request.method == "POST":
        user = db.execute("SELECT * FROM users WHERE username = ?", request.form.get("username"))
        if not user or not check_password_hash(user[0]["hash"], request.form.get("password")):
            return "Invalid login"
        session["user_id"] = user[0]["id"]
        return redirect("/")
    return render_template("index.html", page="login")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        if db.execute("SELECT * FROM users WHERE username = ?", request.form.get("username")):
            return "Username already exists"
        db.execute(
            "INSERT INTO users (username, hash, email) VALUES (?, ?, ?)",
            request.form.get("username"),
            generate_password_hash(request.form.get("password")),
            request.form.get("email")
        )
        return redirect("/login")
    return render_template("index.html", page="register")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

if __name__ == "__main__":
    app.run(debug=True)