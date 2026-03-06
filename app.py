import os
import json
import hashlib
import requests

from flask import Flask, request, jsonify, render_template, redirect
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_cors import CORS
from flask_dance.contrib.google import make_google_blueprint, google


# ---------------- APP SETUP ---------------- #

app = Flask(__name__)
CORS(app)
app.secret_key = os.getenv("SECRET_KEY", "eco_switch_secret")


# ---------------- API CONFIG ---------------- #

HF_API_KEY = os.getenv("HF_API_KEY")
HF_MODEL = "meta-llama/Meta-Llama-3-8B-Instruct"
HF_URL = "https://router.huggingface.co/v1/chat/completions"

HEADERS = {
    "Authorization": f"Bearer {HF_API_KEY}",
    "Content-Type": "application/json"
} if HF_API_KEY else {}

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
TAVILY_URL = "https://api.tavily.com/search"

print("HF_API_KEY loaded:", bool(HF_API_KEY))
print("TAVILY_API_KEY loaded:", bool(TAVILY_API_KEY))


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

    if email not in users:
        users[email] = {
            "password": None,
            "points": 0,
            "co2_saved": 0,
            "level": "Eco Beginner",
            "name": name,
            "picture": picture,
        }

    login_user(User(email))

    with open("users.json", "w") as f:
        json.dump(users, f, indent=2)

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


# ---------------- UTILITIES ---------------- #

def detect_product_type_fallback(text):

    text = text.lower()

    if "hoodie" in text: return "hoodie"
    if "jacket" in text: return "jacket"
    if "shirt" in text: return "shirt"
    if "jean" in text: return "jeans"
    if "sweater" in text: return "sweater"
    if "sneaker" in text or "shoe" in text: return "sneakers"

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


# ---------------- AI EXTRACTION ---------------- #

def ai_extract_product(user_input):

    if not HF_API_KEY:
        return None

    prompt = f"""
Extract Material and Product_Type.

Return JSON:
{{"Material":"cotton","Product_Type":"hoodie"}}

Product: {user_input}
"""

    try:

        response = requests.post(
            HF_URL,
            headers=HEADERS,
            json={
                "model": HF_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 200
            },
            timeout=30
        )

        if response.status_code != 200:
            return None

        result = response.json()

        text = result["choices"][0]["message"]["content"].strip()

        start = text.find("[")
        end = text.rfind("]")

        if start == -1 or end == -1:
            print("AI returned non-JSON:", text)
            return []

        json_text = text[start:end+1]

        try:
            parsed = json.loads(json_text)
        except Exception as e:
            print("JSON parsing failed:", json_text)
            return []

        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end])
            except:
                return None

    except Exception as e:
        print("AI extraction error:", e)

    return None


# ---------------- TAVILY SEARCH ---------------- #

def tavily_search(query):

    if not TAVILY_API_KEY:
        return []

    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": "advanced",
        "max_results": 5
    }

    try:

        response = requests.post(TAVILY_URL, json=payload, timeout=20)

        data = response.json()

        results = []

        for r in data.get("results", []):
            results.append({
                "title": r.get("title"),
                "url": r.get("url"),
                "content": r.get("content")
            })

        return results

    except Exception as e:
        print("Tavily error:", e)
        return []


# ---------------- AI RANK WEB RESULTS ---------------- #

def ai_rank_web_results(user_product, search_results):

    if not search_results:
        return []

    prompt = f"""
User wants a sustainable alternative to:
{user_product}

Here are web results:
{json.dumps(search_results)}

Pick the 3 best sustainable product alternatives.

Return ONLY JSON:

[
 {{
   "product_name":"...",
   "brand":"...",
   "reason":"..."
 }}
]
"""

    try:

        response = requests.post(
            HF_URL,
            headers=HEADERS,
            json={
                "model": HF_MODEL,
                "messages": [
                    {"role": "system", "content": "Return only JSON."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.2,
                "max_tokens": 300
            }
        )

        result = response.json()

        text = result["choices"][0]["message"]["content"]

        start = text.find("[")
        end = text.rfind("]")

        if start == -1 or end == -1:
            return []

        parsed = json.loads(text[start:end+1])

        # attach urls from search results
        for i, alt in enumerate(parsed):

            if i < len(search_results):
                alt["url"] = search_results[i]["url"]
            else:
                alt["url"] = ""

        return parsed

    except Exception as e:
        print("AI ranking error:", e)
        return []


# ---------------- ANALYZE ---------------- #

@app.route("/analyze", methods=["POST"])
@login_required
def analyze():

    data = request.get_json(silent=True) or {}
    user_input = data.get("input", "")

    ai_data = ai_extract_product(user_input)

    material = ""
    product_type = ""

    if ai_data:
        material = ai_data.get("Material", "").lower()
        product_type = ai_data.get("Product_Type", "").lower()

    if not product_type:
        product_type = detect_product_type_fallback(user_input)

    material_info = materials_db.get(material, {"estimated_co2": 10})

    co2_original = material_info["estimated_co2"]

    query = f"buy sustainable {product_type} eco friendly {product_type}"

    search_results = tavily_search(query)

    alternatives = ai_rank_web_results(user_input, search_results)

    if not alternatives:

        db_alts = sustainability_db.get("fashion", [])

        filtered = [
            item for item in db_alts
            if item.get("product_type","").lower() == product_type
        ]

        alternatives = sorted(filtered, key=lambda x: x["estimated_co2"])[:3]

        for alt in alternatives:
            alt["url"] = ""
            alt["reason"] = alt.get("why_lower_impact", "")
    if alternatives:
        user_data = update_user(
            current_user.id,
            co2_original,
            alternatives[0].get("estimated_co2", 5)
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
        "user": user_data
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
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)