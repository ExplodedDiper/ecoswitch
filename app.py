import os
import requests
import json
import hashlib

from flask import Flask, request, jsonify, render_template, redirect
from flask_cors import CORS
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_dance.contrib.google import make_google_blueprint, google

# ---------------- APP SETUP ---------------- #

app = Flask(__name__)
CORS(app)
app.secret_key = os.getenv("SECRET_KEY", "eco_switch_super_secret_key")

# ---------------- HUGGING FACE CONFIG ---------------- #

HF_API_KEY = os.getenv("HF_API_KEY")
HF_MODEL = "google/flan-t5-base"
HF_URL = f"https://router.huggingface.co/v1/models/{HF_MODEL}"
HEADERS = {"Authorization": f"Bearer {HF_API_KEY}"} if HF_API_KEY else {}


print("HF_API_KEY value:", HF_API_KEY)

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
    ],
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
        return "Google did not return email."

    if email not in users:
        users[email] = {
            "password": None,
            "points": 0,
            "co2_saved": 0,
            "level": "Eco Beginner",
            "name": name,
            "picture": picture,
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
            "picture": None,
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


# ---------------- AI FUNCTIONS ---------------- #

def ai_extract_product(product_text):
    if not HF_API_KEY:
        print("HF_API_KEY missing")
        return None

    prompt = f"""
Extract:
- Material
- Product_Type

Return ONLY valid JSON.

Product:
{product_text}
"""

    try:
        response = requests.post(
            HF_URL,
            headers=HEADERS,
            json={
                "inputs": prompt,
                "parameters": {
                    "temperature": 0.2,
                    "max_new_tokens": 200,
                    "return_full_text": False
                }
            },
            timeout=30
        )

        print("HF STATUS:", response.status_code)
        print("HF RAW RESPONSE:", response.text)

        return None  # temporarily stop parsing

    except Exception as e:
        print("HF ERROR:", str(e))
        return None

def ai_rerank_candidates(product_text, candidates):
    if not HF_API_KEY or not candidates:
        return candidates[:3]

    prompt = f"""
User is buying:
{product_text}

Here are sustainable alternatives:
{json.dumps(candidates)}

Pick the 3 best matches.
Return ONLY valid JSON list.
"""

    try:
        response = requests.post(
            HF_URL,
            headers=HEADERS,
            json={
                "inputs": prompt,
                "parameters": {
                    "temperature": 0.2,
                    "max_new_tokens": 300,
                    "return_full_text": False
                }
            },
            timeout=20
        )

        result = response.json()
        text_output = result[0].get("generated_text", "")

        start = text_output.find("[")
        end = text_output.rfind("]") + 1

        if start == -1 or end == -1:
            return candidates[:3]

        return json.loads(text_output[start:end])

    except:
        return candidates[:3]


# ---------------- ANALYZE ROUTE ---------------- #

@app.route("/analyze", methods=["POST"])
@login_required
def analyze():

    data = request.json
    product_text = data.get("input", "")

    # 1️⃣ Extract using AI
    ai_data = ai_extract_product(product_text)
    print("AI extraction output:", ai_data)
    material = ""
    product_type = ""

    if ai_data:
        material = ai_data.get("Material", "").lower()
        product_type = ai_data.get("Product_Type", "").lower()

    # 2️⃣ Fallback if AI fails
    if not product_type:
        product_type = detect_product_type_fallback(product_text)

    material_info = materials_db.get(material, {"estimated_co2": 10})
    co2_original = material_info["estimated_co2"]

    # 3️⃣ DB filtering
    db_alts = sustainability_db.get("fashion", [])

    filtered = [
        item for item in db_alts
        if product_type and product_type in item.get("product_type", "").lower()
    ]
    print("Filtered candidates:", filtered)
    candidates = sorted(filtered, key=lambda x: x["estimated_co2"])[:5]

    # 4️⃣ AI reranking
    alternatives = ai_rerank_candidates(product_text, candidates)

    if not alternatives and candidates:
        alternatives = candidates[:3]
    print("Final alternatives:", alternatives)
    # 5️⃣ Update user
    if alternatives:
        user_data = update_user(
            current_user.id,
            co2_original,
            alternatives[0]["estimated_co2"]
        )
    else:
        user_data = users[current_user.id]

    return jsonify({
        "product_metrics": {
            "material": material or "-",
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
    user_data = users.get(current_user.id) if current_user.is_authenticated else None
    return render_template("home.html", user=user_data)


@app.route("/analyzer")
@login_required
def analyzer():
    user_data = users.get(current_user.id)
    return render_template("analyzer.html", user=user_data)


# ---------------- RUN ---------------- #

if __name__ == "__main__":
    app.run(debug=True)