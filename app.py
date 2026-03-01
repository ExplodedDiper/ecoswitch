import os
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'  # Allow HTTP for local dev only

from flask import Flask, request, jsonify, render_template, redirect
from flask_cors import CORS
import json
import hashlib

from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_dance.contrib.google import make_google_blueprint, google

app = Flask(__name__)
CORS(app)

app.secret_key = "eco_switch_super_secret_key"

# ---------------- LOAD DATA ---------------- #

if os.path.exists("users.json"):
    with open("users.json") as f:
        users = json.load(f)
else:
    users = {}

with open("sustainability_db.json") as f:
    sustainability_db = json.load(f)

with open("materials_impact.json") as f:
    materials_db = json.load(f)

# ---------------- LOGIN SYSTEM ---------------- #

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

class User(UserMixin):
    def __init__(self, email):
        self.id = email

@login_manager.user_loader
def load_user(user_id):
    if user_id in users:
        return User(user_id)
    return None

# ---------------- GOOGLE LOGIN ---------------- #

google_bp = make_google_blueprint(
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    redirect_to="google_login",
    scope=[
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
    ]
)

app.register_blueprint(google_bp, url_prefix="/login")

@app.route("/google_login")
def google_login():
    if not google.authorized:
        return redirect("/login/google")

    resp = google.get("https://www.googleapis.com/oauth2/v2/userinfo")
    info = resp.json()

    email = info.get("email")
    name = info.get("name")
    picture = info.get("picture")

    if not email:
        return "Google did not return email. Check OAuth scope."

    if email not in users:
        users[email] = {
            "password": None,
            "points": 0,
            "co2_saved": 0,
            "level": "Eco Beginner",
            "name": name,
            "picture": picture
        }
    else:
        users[email]["name"] = name
        users[email]["picture"] = picture

    with open("users.json", "w") as f:
        json.dump(users, f, indent=2)

    login_user(User(email))
    return redirect("/")

# ---------------- REGISTER ---------------- #

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"]
        name = request.form["name"]
        password = hashlib.sha256(request.form["password"].encode()).hexdigest()

        if email in users:
            return "User already exists"

        users[email] = {
            "password": password,
            "points": 0,
            "co2_saved": 0,
            "level": "Eco Beginner",
            "name": name,
            "picture": None
        }

        with open("users.json", "w") as f:
            json.dump(users, f, indent=2)

        return redirect("/login")

    return render_template("register.html")

# ---------------- LOGIN ---------------- #

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = hashlib.sha256(request.form["password"].encode()).hexdigest()

        if email in users and users[email]["password"] == password:
            login_user(User(email))
            return redirect("/")

        return "Invalid credentials"

    return render_template("login.html")

# ---------------- LOGOUT ---------------- #

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect("/")

# ---------------- PRODUCT LOGIC ---------------- #

def detect_product_type_fallback(text):
    text = text.lower()
    if "hoodie" in text: return "hoodie"
    if "jacket" in text: return "jacket"
    if "shirt" in text or "t-shirt" in text: return "shirt"
    if "jean" in text: return "jeans"
    if "sweater" in text: return "sweater"
    if "legging" in text: return "leggings"
    if "shoe" in text or "sneaker" in text: return "shoes"
    return ""

def update_user(email, co2_original, co2_alt):
    diff = max(co2_original - co2_alt, 0)
    users[email]["points"] += diff * 5
    users[email]["co2_saved"] += diff

    if users[email]["points"] > 300:
        users[email]["level"] = "Planet Protector"
    elif users[email]["points"] > 100:
        users[email]["level"] = "Eco Explorer"

    with open("users.json", "w") as f:
        json.dump(users, f, indent=2)

    return users[email]

@app.route("/analyze", methods=["POST"])
@login_required
def analyze():
    data = request.json
    user_input = data.get("input", "")

    product_type = detect_product_type_fallback(user_input)

    db_alts = sustainability_db.get("fashion", [])
    filtered = [
        item for item in db_alts
        if product_type in item.get("product_type", "").lower()
    ]

    alternatives = sorted(filtered, key=lambda x: x["estimated_co2"])[:3]

    co2_original = 10

    if alternatives:
        user_data = update_user(current_user.id, co2_original, alternatives[0]["estimated_co2"])
    else:
        user_data = users[current_user.id]

    return jsonify({
        "product_metrics": {
            "material": "-",
            "estimated_co2": co2_original,
            "detected_product_type": product_type
        },
        "alternatives": alternatives,
        "user": user_data,
        "disclaimer": "All sustainability insights are derived from publicly available datasets and certification bodies. This tool does not rank, criticize, or endorse brands."
    })

# ---------------- MAIN ROUTES ---------------- #

@app.route("/")
def home():
    user_data = None
    if current_user.is_authenticated:
        user_data = users.get(current_user.id)
    return render_template("home.html", user=user_data)

@app.route("/analyzer")
@login_required
def analyzer():
    user_data = users.get(current_user.id)
    return render_template("analyzer.html", user=user_data)

# ---------------- RUN ---------------- #

if __name__ == "__main__":
    app.run(debug=True)