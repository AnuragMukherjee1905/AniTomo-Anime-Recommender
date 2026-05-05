# 🎌 Anime Recommender System

A full-stack anime recommendation system that suggests shows based on your preferences using a mix of machine learning techniques and a dynamic web interface.

Built with **FastAPI (backend)** and a **vanilla JavaScript frontend**, this project focuses on delivering a complete pipeline — from data collection to model inference to user interaction.

---

## ✨ What this project does

Ever struggled to find what anime to watch next?
This system helps by recommending anime based on:

* 🎭 Selected **genres**
* 🎯 Chosen **mood**
* ❤️ Previously liked anime (optional)
* 🔍 Direct **search queries**

It combines both **content-based filtering** and **collaborative filtering** to generate meaningful suggestions instead of random lists.

---

## 🧠 How it works (High-level)

### 1. 📦 Data Collection

Anime data is fetched using the **Jikan API** and stored locally in CSV format.

---

### 2. 🧩 Recommendation Engine

The backend uses a **hybrid recommendation approach**:

#### 🔹 Content-Based Filtering

* Uses **TF-IDF** on anime descriptions
* Encodes genres using **multi-label binarization**
* Computes similarity using **cosine similarity**

#### 🔹 Collaborative Filtering

* Uses **ALS (Alternating Least Squares)** via the `implicit` library
* Learns patterns from user–anime interactions

#### 🔹 Hybrid Scoring

Final score is a blend of both approaches:

```
final_score = α * content_score + (1 - α) * collaborative_score
```

---

### 3. ⚡ Backend (FastAPI)

The backend exposes APIs like:

* `/recommend` → personalized recommendations
* `/search` → search anime by title
* `/trending` → top-rated anime
* `/anime/{id}/similar` → similar anime

---

### 4. 🎨 Frontend (JavaScript)

* Dynamic UI built using vanilla JS
* Fetches data from backend APIs
* Displays results as **interactive cards**
* Includes a **modal popup** for detailed anime info

---

## 🚀 Features

*  Hybrid recommendation system (content + collaborative)
*  Mood-based filtering
*  Real-time search functionality
*  Anime cards with images and details
*  Modal view for expanded information
*  FastAPI backend with async support

---

## 🛠️ Tech Stack

**Backend**

* FastAPI
* Pandas, NumPy, SciPy
* Scikit-learn
* Implicit (ALS)

**Frontend**

* HTML, CSS, JavaScript

**Data Source**

* Jikan API (MyAnimeList)

---

## 🧪 Running the Project Locally

### 1. Download the project

Click the **Code → Download ZIP** button on GitHub and extract it.


### 2. Create virtual environment (recommended)

```bash
py -3.11 -m venv venv
venv\Scripts\activate

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

---

### 4. Generate dataset

```bash
python jikan_scraper.py
```

---

### 5. Run the backend

```bash
python -m uvicorn main:app --reload
```

---

### 6. Run frontend

Open `index.html` in your browser
(or use a local server like `python -m http.server`)

---

## ⚠️ Important Note

This project uses the `implicit` library for collaborative filtering.

👉 Recommended Python version:

```
Python 3.11
```

Newer versions (like 3.14) may cause installation issues.

---

## 📌 Project Highlights

* Built a **complete ML pipeline** from scratch
* Implemented **hybrid recommendation logic**
* Integrated **backend APIs with frontend UI**
* Focused on **real-world usability and performance**

---

## 💡 Future Improvements

* User accounts & watch history
* Better personalization with user feedback
* Deployment (Docker / cloud hosting)
* Improved UI/UX animations

---

## 🙌 Final Thoughts

This project was built to understand how recommendation systems actually work in practice — not just the theory, but how everything connects:

```
Data → Model → API → UI
```

---

If you found this useful or interesting, feel free to ⭐ the repo!
