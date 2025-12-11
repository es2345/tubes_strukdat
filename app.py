from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_
from sqlalchemy import func
from sqlalchemy.sql import func
from werkzeug.utils import secure_filename
from datetime import datetime
import os
from mutagen import File as MutagenFile
from collections import defaultdict
import urllib.parse
from flask import request


#Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
import os

app = Flask(__name__)
app.secret_key = "rahasia-dev"  # ganti dengan nilai random untuk production

# ================== DATABASE CONFIG ==================
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "app.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
AUDIO_FOLDER = os.path.join(BASE_DIR, "audio")
os.makedirs(AUDIO_FOLDER, exist_ok=True)
app.config["AUDIO_UPLOAD_FOLDER"] = AUDIO_FOLDER

ALLOWED_AUDIO_EXTENSIONS = {"mp3", "wav", "ogg", "m4a"}

COVER_FOLDER = os.path.join(BASE_DIR, "covers")
os.makedirs(COVER_FOLDER, exist_ok=True)
app.config["COVER_UPLOAD_FOLDER"] = COVER_FOLDER

ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif"}


db = SQLAlchemy(app)

# ================== MODELS ==================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    display_name = db.Column(db.String(80), nullable=False)
    password = db.Column(db.String(80), nullable=False)  # TODO: hash
    role = db.Column(db.String(20), default="user")
    avatar_url = db.Column(db.String(255), nullable=True)
    playlists = db.relationship("Playlist", backref="owner", lazy=True)
    folders = db.relationship("Folder", backref="owner", lazy=True)



class Folder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    playlists = db.relationship("Playlist", backref="folder", lazy=True)



playlist_song = db.Table(
    "playlist_song",
    db.Column("playlist_id", db.Integer, db.ForeignKey("playlist.id"), primary_key=True),
    db.Column("song_id", db.Integer, db.ForeignKey("song.id"), primary_key=True),
    db.Column("added_at", db.DateTime, default=datetime.utcnow)
)


class Playlist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    folder_id = db.Column(db.Integer, db.ForeignKey("folder.id"), nullable=True)

    cover_url = db.Column(db.String(500))

    # many-to-many ke Song
    songs = db.relationship(
        "Song",
        secondary=playlist_song,
        back_populates="playlists",
        lazy="dynamic"   # atau True biasa
    )


class Song(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    artist = db.Column(db.String(120), nullable=False)
    album = db.Column(db.String(120))
    genre = db.Column(db.String(50))
    year = db.Column(db.Integer)
    duration_ms = db.Column(db.Integer)

    cover_url = db.Column(db.String(500))
    audio_url = db.Column(db.String(500))
    description = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # daftar playlist yang berisi lagu ini
    playlists = db.relationship(
        "Playlist",
        secondary=playlist_song,
        back_populates="songs"
    )

class ArtistProfile(db.Model):
    __tablename__ = "artist_profiles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), unique=True, nullable=False)
    avatar_url = db.Column(db.String(255), nullable=True)
    bio = db.Column(db.Text, nullable=True)




# ================== HELPER FUNCTIONS ==================

def get_current_user():
    email = session.get("user_email")
    if not email:
        return None
    return User.query.filter_by(email=email).first()


def get_or_create_artist_profile(artist_name: str) -> ArtistProfile:
    artist_name = (artist_name or "").strip()
    if not artist_name:
        return None

    profile = ArtistProfile.query.filter_by(name=artist_name).first()
    if profile:
        return profile

    profile = ArtistProfile(name=artist_name)
    db.session.add(profile)
    db.session.commit()
    return profile


@app.route("/artist/<artist_name>", methods=["GET", "POST"])
def artist_profile_page(artist_name):
    user = get_current_user()
    if not user:
        session.clear()
        return redirect(url_for("login"))

    # decode dari URL
    artist_name = urllib.parse.unquote(artist_name)

    profile = get_or_create_artist_profile(artist_name)
    if not profile:
        return redirect(url_for("home_page"))

    if request.method == "POST":
        # ganti nama artist (optional)
        new_name = (request.form.get("display_name") or "").strip()
        if new_name:
            profile.name = new_name

        # upload avatar baru
        avatar = request.files.get("avatar")
        if avatar and avatar.filename:
            filename = secure_filename(avatar.filename)
            save_dir = os.path.join(app.static_folder, "artist_avatars")
            os.makedirs(save_dir, exist_ok=True)
            save_path = os.path.join(save_dir, filename)
            avatar.save(save_path)

            profile.avatar_url = f"artist_avatars/{filename}"

        db.session.commit()
        # redirect ke nama baru kalau diubah
        return redirect(url_for("artist_profile_page", artist_name=profile.name))

    # Semua lagu milik artist ini
    songs = Song.query.filter(Song.artist == profile.name).all()

    return render_template(
        "artist_profile.html",
        current_user=user,
        artist=profile,
        songs=songs,
    )

# struktur data hashmap

def get_recommended_songs_for_user(user, limit: int = 20):
    """
    Algoritma rekomendasi sederhana berbasis konten:
    - pakai hash map (dict) untuk menyimpan preferensi artist & genre user
    - sumber preferensi = lagu-lagu di playlist user
    - hasil: list Song yang belum ada di playlist user, diurutkan dari skor tertinggi
    """

    # 1. Kumpulkan semua lagu di playlist user
    user_playlists = Playlist.query.filter_by(user_id=user.id).all()
    user_song_ids = set()

    for pl in user_playlists:
        # pl.songs adalah relationship lazy="dynamic", bisa langsung di-iterate
        for song in pl.songs:
            user_song_ids.add(song.id)

    # Kalau user belum punya lagu di playlist → fallback lagu terbaru global
    if not user_song_ids:
        return (
            Song.query
            .order_by(Song.id.desc())
            .limit(limit)
            .all()
        )

    # 2. Bangun hash map preferensi artist & genre
    artist_pref = defaultdict(int)  # hash map: artist -> count
    genre_pref = defaultdict(int)   # hash map: genre -> count

    user_songs = Song.query.filter(Song.id.in_(user_song_ids)).all()
    for s in user_songs:
        artist_key = (s.artist or "").strip().lower()
        genre_key = (s.genre or "").strip().lower()

        if artist_key:
            artist_pref[artist_key] += 1
        if genre_key:
            genre_pref[genre_key] += 1

    # 3. Kandidat: semua lagu yang belum ada di playlist user
    all_songs = Song.query.all()
    candidates = [s for s in all_songs if s.id not in user_song_ids]

    scored = []
    for s in candidates:
        artist_key = (s.artist or "").strip().lower()
        genre_key = (s.genre or "").strip().lower()

        # skor pakai hash map
        score = 0
        score += artist_pref.get(artist_key, 0) * 3   # artist lebih berat
        score += genre_pref.get(genre_key, 0) * 2     # genre sedikit lebih ringan

        # skip lagu yang sama sekali nggak nyambung
        if score <= 0:
            continue

        scored.append((score, s))

    # Kalau ternyata nggak ada kandidat yang punya skor > 0 → fallback global lagi
    if not scored:
        return (
            Song.query
            .order_by(Song.id.desc())
            .limit(limit)
            .all()
        )

    # 4. Urutkan berdasarkan skor (desc), tie-break pakai created_at/id
    scored.sort(
        key=lambda item: (
            item[0],                                   # skor
            item[1].created_at or datetime.min,       # lebih baru sedikit diutamakan
            item[1].id                                # tie-break terakhir
        ),
        reverse=True,
    )

    # Ambil top-N
    top_songs = [s for _, s in scored[:limit]]
    return top_songs


def get_recommended_songs_for_playlist(playlist, limit: int = 20):
    """
    Rekomendasi berbasis konten untuk 1 playlist.
    - Preferensi diambil dari lagu-lagu di playlist ini.
    - Fitur: artist + genre.
    - Hasil: lagu-lagu yang BELUM ada di playlist ini.
    """
    if not playlist:
        return []

    # 1. ID semua lagu yang SUDAH ada di playlist ini
    playlist_song_ids = {s.id for s in playlist.songs}

    # Kalau playlist kosong → fallback: lagu terbaru global
    if not playlist_song_ids:
        return (
            Song.query
            .order_by(Song.id.desc())
            .limit(limit)
            .all()
        )

    # 2. Hitung preferensi artist & genre
    artist_pref = defaultdict(int)
    genre_pref = defaultdict(int)

    for s in playlist.songs:
        artist_key = (s.artist or "").strip().lower()
        genre_key  = (s.genre  or "").strip().lower()

        if artist_key:
            artist_pref[artist_key] += 1
        if genre_key:
            genre_pref[genre_key] += 1

    # 3. Kandidat = SEMUA lagu, kecuali yang sudah ada di playlist
    all_songs = Song.query.all()
    candidates = [s for s in all_songs if s.id not in playlist_song_ids]

    scored = []
    for s in candidates:
        artist_key = (s.artist or "").strip().lower()
        genre_key  = (s.genre  or "").strip().lower()

        score = 0
        score += artist_pref.get(artist_key, 0) * 3   # kecocokan artist
        score += genre_pref.get(genre_key, 0) * 2     # kecocokan genre

        # Kalau sama sekali nggak nyambung, skip
        if score <= 0:
            continue

        scored.append((score, s))

    # 4. Kalau nggak ada hasil setelah diskor → benar-benar tidak ada rekomendasi
    if not scored:
        return []   # <-- penting: balikin list kosong

    # 5. Urutkan berdasarkan skor (lalu created_at, lalu id)
    scored.sort(
        key=lambda item: (
            item[0],
            item[1].created_at or datetime.min,
            item[1].id
        ),
        reverse=True,
    )

    return [s for _, s in scored[:limit]]



def allowed_image_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def allowed_audio_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_AUDIO_EXTENSIONS

@app.route("/covers/<path:filename>")
def serve_cover(filename):
    return send_from_directory(app.config["COVER_UPLOAD_FOLDER"], filename)


def create_default_admin():
    """Bikin admin default kalau belum ada."""
    admin = User.query.filter_by(email="admin@example.com").first()
    if not admin:
        admin = User(
            email="admin@example.com",
            display_name="Admin",
            password="admin123",
            role="admin",
        )
        db.session.add(admin)
        db.session.commit()


def create_default_library():
    """Bikin contoh folder & playlist untuk admin, biar sidebar nggak kosong."""
    admin = User.query.filter_by(email="admin@example.com").first()
    if not admin:
        return

    # kalau admin belum punya playlist sama sekali, bikin contoh
    has_playlist = Playlist.query.filter_by(user_id=admin.id).first()
    if has_playlist:
        return

    folder = Folder(name="New Folder", user_id=admin.id)
    db.session.add(folder)
    db.session.commit()

    p1 = Playlist(name="My Playlist #5", user_id=admin.id, folder_id=folder.id)
    p2 = Playlist(name="Chill Vibes", user_id=admin.id, folder_id=None)

    db.session.add_all([p1, p2])
    db.session.commit()



@app.route("/playlist/<int:playlist_id>/add-song/<int:song_id>", methods=["POST"])
def add_song_to_playlist(playlist_id, song_id):
    user = get_current_user()
    if not user:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "error": "AUTH_REQUIRED"}), 401
        return redirect(url_for("login"))

    playlist = Playlist.query.filter_by(id=playlist_id, user_id=user.id).first_or_404()
    song = Song.query.get_or_404(song_id)

    # --- CEK DUPLIKAT YANG BENAR UNTUK lazy="dynamic" ---
    if hasattr(playlist.songs, "filter_by"):
        existing = playlist.songs.filter_by(id=song.id).first()
    else:
        existing = song if song in playlist.songs else None

    added = False
    if existing is None:
        playlist.songs.append(song)
        db.session.commit()
        added = True   # hanya True kalau benar-benar baru

    # kalau dipanggil via AJAX
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        duration_label = None
        if song.duration_ms:
            total_sec = song.duration_ms // 1000
            mins = total_sec // 60
            secs = total_sec % 60
            duration_label = f"{mins}:{secs:02d}"

        return jsonify({
            "success": True,
            "added": added,
            "playlist_id": playlist.id,
            "song": {
                "id": song.id,
                "title": song.title,
                "artist": song.artist or "Unknown artist",
                "album": song.album,
                "duration_ms": song.duration_ms,
                "duration_label": duration_label,
                "cover_url": song.cover_url or url_for(
                    "serve_cover", filename="default_cover.png"
                ),
                "audio_url": song.audio_url,
            },
        })

    # fallback kalau bukan AJAX
    next_url = request.form.get("next")
    if next_url:
        return redirect(next_url)
    return redirect(url_for("song_page", song_id=song.id))



# ================== ROUTES ==================

@app.route("/")
def index():
    # kalau sudah login, langsung ke /home
    if "user_email" in session:
        return redirect(url_for("home_page"))
    # kalau mau landing page khusus, bisa ganti ke render_template("index.html")
    return redirect(url_for("login"))

@app.route("/audio/<path:filename>")
def serve_audio(filename):
    return send_from_directory(app.config["AUDIO_UPLOAD_FOLDER"], filename)

# ---------- SIGNUP ----------
@app.route("/signup", methods=["GET", "POST"])
def signup():
    error = None

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        display_name = (request.form.get("display_name") or "").strip()

        # validasi basic
        if not email or not password:
            error = "Email dan password wajib diisi."
            return render_template("signup.html", error=error)

        # cek email sudah ada apa belum
        existing = User.query.filter_by(email=email).first()
        if existing:
            error = "Email sudah terdaftar."
            return render_template("signup.html", error=error)

        if not display_name:
            display_name = email.split("@")[0]

        # simpan ke database
        user = User(
            email=email,
            display_name=display_name,
            password=password,   # nanti bisa diganti hash
            role="user",
        )
        db.session.add(user)
        db.session.commit()

        # auto-login lalu ke /home
        session["user_email"] = user.email
        return redirect(url_for("home_page"))

    # GET pertama kali
    return render_template("signup.html", error=error)


@app.route("/search")
def search_results_page():
    user = get_current_user()
    if not user:
        session.clear()
        return redirect(url_for("login"))

    q = (request.args.get("q") or "").strip()
    if not q:
        return redirect(url_for("home_page"))

    # SONG RESULTS
    song_results = (
        Song.query
        .filter(
            or_(
                Song.title.ilike(f"%{q}%"),
                Song.artist.ilike(f"%{q}%"),
                Song.album.ilike(f"%{q}%"),
            )
        )
        .order_by(Song.title.asc())
        .all()
    )


    # ==== ARTIST RESULTS ====
    artist_rows = (
        db.session.query(Song.artist)
        .filter(Song.artist.ilike(f"%{q}%"))
        .distinct()
        .limit(10)
        .all()
    )

    artist_names = [row[0] for row in artist_rows if row[0]]

# ambil profil artist yang sudah pernah dibuat
    profiles = ArtistProfile.query.filter(ArtistProfile.name.in_(artist_names)).all()
    profile_by_name = {p.name: p for p in profiles}

    artist_results = []
    for name in artist_names:
        if not name:
            continue

        profile = profile_by_name.get(name)

    # fallback cover: ambil satu lagu apapun dari artist ini yang punya cover
        cover_song = (
            Song.query
            .filter_by(artist=name)
            .filter(Song.cover_url.isnot(None))
            .first()
        )

        avatar_url = None
        if profile and profile.avatar_url:
            avatar_url = url_for("static", filename=profile.avatar_url)
        elif cover_song and cover_song.cover_url:
            avatar_url = cover_song.cover_url

        artist_results.append({
            "name": name,
            "avatar_url": avatar_url,
        })

    

    # playlist_results nanti bisa kamu isi, sementara kosong juga boleh
    playlist_results = []

    top_song = song_results[0] if song_results else None
    featured_playlists = []

    root_playlists = Playlist.query.filter_by(user_id=user.id, folder_id=None).all()
    folders = Folder.query.filter_by(user_id=user.id).all()

    return render_template(
        "search_results.html",
        current_user=user,
        root_playlists=root_playlists,
        folders=folders,
        query=q,
        top_song=top_song,
        song_results=song_results,
        artist_results=artist_results,
        playlist_results=playlist_results,
        featured_playlists=featured_playlists,
    )


# ---------- LOGIN ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        login_id = (request.form.get("login_id") or "").strip().lower()
        password = request.form.get("password") or ""

        if not login_id or not password:
            error = "Email/username dan password wajib diisi."
            return render_template("login.html", error=error)

        user = User.query.filter(
            or_(
                User.email == login_id,
                db.func.lower(User.display_name) == login_id,
            )
        ).first()

        if not user or user.password != password:
            error = "Email/username atau password salah."
            return render_template("login.html", error=error)

        session["user_email"] = user.email
        if user.role == "admin":
            return redirect(url_for("admin_page"))
        return redirect(url_for("home_page"))

    return render_template("login.html", error=error)


# ---------- ADMIN ----------
@app.route("/admin")
def admin_page():
    user = get_current_user()
    if not user:
        session.clear()
        return redirect(url_for("login"))

    # cuma admin yg boleh
    if user.role != "admin":
        return redirect(url_for("home_page"))

    # ====== STATISTIK GLOBAL BERDASARKAN TABEL SONG ======
    total_songs = Song.query.count()

    # total artist unik
    total_artists = (
        db.session.query(func.count(func.distinct(Song.artist)))
        .scalar()
        or 0
    )

    # total album unik (yang tidak NULL / kosong)
    total_albums = (
        db.session.query(func.count(func.distinct(Song.album)))
        .scalar()
        or 0
    )

    # beberapa lagu terakhir yang baru ditambahkan
    recent_songs = (
        Song.query
        .order_by(Song.created_at.desc())
        .limit(5)
        .all()
    )

    return render_template(
        "admin_home.html",
        current_user=user,
        total_songs=total_songs,
        total_artists=total_artists,
        total_albums=total_albums,
        recent_songs=recent_songs,
    )


@app.route("/admin/songs")
def admin_view_all_song():
    user = get_current_user()
    if not user:
        session.clear()
        return redirect(url_for("login"))
    if user.role != "admin":
        return redirect(url_for("home_page"))

    # sementara: ambil semua lagu untuk ditampilkan di tabel
    songs = Song.query.order_by(Song.id.asc()).all()

    return render_template(
        "admin_view_all_song.html",
        current_user=user,
        songs=songs,
    )


@app.route("/admin/add-song", methods=["GET", "POST"])
def admin_add_song():
    user = get_current_user()
    if not user:
        session.clear()
        return redirect(url_for("login"))

    if user.role != "admin":
        return redirect(url_for("home_page"))

    if request.method == "POST":
        # ============ BACA FIELD DARI FORM ============
        title = (request.form.get("title") or "").strip()
        artist = (request.form.get("artist") or "").strip()
        album  = (request.form.get("album") or "").strip()
        genre  = (request.form.get("genre") or "").strip()
        year_raw = (request.form.get("year") or "").strip()
        description = (request.form.get("description") or "").strip()

        errors = []

        if not title:
            errors.append("Title is required.")
        if not artist:
            errors.append("Artist is required.")

        year = None
        if year_raw:
            try:
                year = int(year_raw)
            except ValueError:
                errors.append("Year harus berupa angka.")

        # ====== HANDLE AUDIO FILE (dan durasi otomatis) ======
        audio_file = request.files.get("audio_file")
        audio_url = None
        duration_ms = None

        if audio_file and audio_file.filename:
            if allowed_audio_file(audio_file.filename):
                filename = secure_filename(audio_file.filename)
                name, ext = os.path.splitext(filename)
                unique = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
                filename = f"{name}_{unique}{ext}"

                audio_folder = app.config["AUDIO_UPLOAD_FOLDER"]
                os.makedirs(audio_folder, exist_ok=True)
                file_path = os.path.join(audio_folder, filename)
                audio_file.save(file_path)

                audio_url = url_for("serve_audio", filename=filename)

                # baca durasi otomatis (kalau pakai mutagen)
                try:
                    from mutagen import File as MutagenFile
                    info = MutagenFile(file_path)
                    if info is not None and info.info is not None:
                        duration_ms = int(info.info.length * 1000)
                except Exception as e:
                    print("Gagal baca durasi:", e)
            else:
                errors.append("Format file audio tidak didukung.")

        # ====== HANDLE COVER (URL atau file) ======
        cover_url_input = (request.form.get("cover_url") or "").strip()
        cover_file = request.files.get("cover_file")
        final_cover_url = None

        if cover_file and cover_file.filename:
            if allowed_image_file(cover_file.filename):
                filename = secure_filename(cover_file.filename)
                name, ext = os.path.splitext(filename)
                unique = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
                filename = f"{name}_{unique}{ext}"

                cover_folder = app.config["COVER_UPLOAD_FOLDER"]
                os.makedirs(cover_folder, exist_ok=True)
                cover_path = os.path.join(cover_folder, filename)
                cover_file.save(cover_path)

                final_cover_url = url_for("serve_cover", filename=filename)
            else:
                errors.append("Format gambar cover tidak didukung.")
        elif cover_url_input:
            final_cover_url = cover_url_input

        if errors:
            # hitung next_song_code lagi supaya field Song ID tetap isi
            next_index = db.session.query(func.max(Song.id)).scalar() or 0
            next_song_code = f"S{next_index + 1:03d}"
            return render_template(
                "admin_add_song.html",
                current_user=user,
                errors=errors,
                next_song_code=next_song_code,
            )

        # ====== SIMPAN KE DB (GLOBAL SONG, TANPA PLAYLIST) ======
        song = Song(
            title=title,
            artist=artist,
            album=album or None,
            genre=genre or None,
            year=year,
            duration_ms=duration_ms,
            cover_url=final_cover_url,
            audio_url=audio_url,
            description=description or None,
            # playlist_id TIDAK di-set lagi → lagu global
        )
        db.session.add(song)
        db.session.commit()

        return redirect(url_for("admin_view_all_song"))

    # ============ METHOD GET: hitung Song ID berikutnya ============
    next_index = db.session.query(func.max(Song.id)).scalar() or 0
    next_song_code = f"S{next_index + 1:03d}"

    return render_template(
        "admin_add_song.html",
        current_user=user,
        next_song_code=next_song_code,
    )


@app.route("/admin/edit-song/<int:song_id>", methods=["GET", "POST"])
def admin_edit_song(song_id):
    """Form edit data lagu di library global.

    - Hanya bisa diakses admin.
    - GET  : tampilkan form dengan data lagu.
    - POST : update field basic (title, artist, album, genre, year, duration, audio_url, description).
    """
    user = get_current_user()
    if not user:
        session.clear()
        return redirect(url_for("login"))

    if user.role != "admin":
        return redirect(url_for("home_page"))

    song = Song.query.get_or_404(song_id)

    errors = []

    if request.method == "POST":
        # field dasar
        title = (request.form.get("title") or "").strip()
        artist = (request.form.get("artist") or "").strip()
        album = (request.form.get("album") or "").strip()
        genre = (request.form.get("genre") or "").strip()
        year_raw = (request.form.get("year") or "").strip()
        duration_str = (request.form.get("duration") or "").strip()
        audio_url_raw = (request.form.get("audio_url") or "").strip()
        description = (request.form.get("description") or "").strip()

        if not title:
            errors.append("Title is required.")
        if not artist:
            errors.append("Artist is required.")

        # year (opsional)
        year = None
        if year_raw:
            try:
                year = int(year_raw)
            except ValueError:
                errors.append("Year harus berupa angka.")

        # parsing durasi mm:ss -> duration_ms
        duration_ms = song.duration_ms
        if duration_str:
            try:
                parts = duration_str.split(":")
                if len(parts) == 2:
                    mins = int(parts[0].strip() or "0")
                    secs = int(parts[1].strip() or "0")
                elif len(parts) == 1:
                    mins = int(parts[0].strip() or "0")
                    secs = 0
                else:
                    raise ValueError("Format durasi tidak valid")

                if mins < 0 or secs < 0 or secs >= 60:
                    raise ValueError("Nilai durasi di luar range")

                total_seconds = mins * 60 + secs
                duration_ms = total_seconds * 1000
            except Exception:
                errors.append("Duration harus dalam format mm:ss, misalnya 3:45.")

        if errors:
            # render ulang dengan pesan error
            return render_template(
                "admin_edit_song.html",
                current_user=user,
                song=song,
                errors=errors,
            )

        # update field ke model
        song.title = title
        song.artist = artist
        song.album = album or None
        song.genre = genre or None
        song.year = year
        song.duration_ms = duration_ms

        # hanya update audio_url kalau field diisi
        if audio_url_raw:
            song.audio_url = audio_url_raw

        song.description = description or None

        db.session.commit()
        return redirect(url_for("admin_view_all_song"))

    # GET: tampilkan form dengan data existing
    return render_template(
        "admin_edit_song.html",
        current_user=user,
        song=song,
        errors=errors,
    )


@app.route("/admin/delete-song/<int:song_id>", methods=["POST"])
def admin_delete_song(song_id):
    """Hapus satu lagu dari library global."""
    user = get_current_user()
    if not user:
        session.clear()
        return redirect(url_for("login"))

    if user.role != "admin":
        return redirect(url_for("home_page"))

    song = Song.query.get_or_404(song_id)

    # lepas lagu dari semua playlist dulu supaya relasi many-to-many bersih
    for pl in list(song.playlists):
        pl.songs.remove(song)

    db.session.delete(song)
    db.session.commit()

    return redirect(url_for("admin_view_all_song"))


# ---------- profile ----------
AVATAR_DIR = os.path.join(app.root_path, "static", "avatars")
os.makedirs(AVATAR_DIR, exist_ok=True)

def allowed_image(filename):
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in {"png", "jpg", "jpeg", "webp", "gif"}


@app.route("/profile", methods=["GET", "POST"])
def profile_page():
    user = get_current_user()
    if not user:
        session.clear()
        return redirect(url_for("login"))

    if request.method == "POST":
        # ----- update display name -----
        display_name = (request.form.get("display_name") or "").strip()
        if display_name:
            user.display_name = display_name

        # ----- update avatar (optional) -----
        file = request.files.get("avatar")
        if file and file.filename:
            if allowed_image(file.filename):
                base = secure_filename(file.filename)
                name, ext = os.path.splitext(base)
                unique = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
                filename = f"{user.id}_{unique}{ext}"

                save_path = os.path.join(AVATAR_DIR, filename)
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                file.save(save_path)

                # disimpan relatif dari /static agar bisa dipakai url_for('static', ...)
                user.avatar_url = f"avatars/{filename}"

        db.session.commit()
        return redirect(url_for("profile_page"))

    # ----- GET: data buat sidebar & isi profil -----
    root_playlists = Playlist.query.filter_by(
        user_id=user.id, folder_id=None
    ).all()
    folders = Folder.query.filter_by(user_id=user.id).all()

    # semua playlist milik user (dipakai Public Playlists di profile.html)
    user_playlists = Playlist.query.filter_by(user_id=user.id).all()

    return render_template(
        "profile.html",
        user=user,
        current_user=user,
        user_playlists=user_playlists,
        root_playlists=root_playlists,
        folders=folders,
    )


# ---------- settings ----------
@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    user = get_current_user()
    if not user:
        session.clear()
        return redirect(url_for("login"))

    if request.method == "POST":
        new_name = (request.form.get("display_name") or "").strip()
        if new_name:
            user.display_name = new_name
            db.session.commit()
        return redirect(url_for("settings_page"))

    root_playlists = Playlist.query.filter_by(
        user_id=user.id, folder_id=None
    ).all()
    folders = Folder.query.filter_by(user_id=user.id).all()

    return render_template(
        "setting.html",
        user=user,
        current_user=user,
        root_playlists=root_playlists,
        folders=folders,
    )




# ---------- API -----------
@app.route("/api/library/folders", methods=["POST"])
def api_create_folder():
    user = get_current_user()
    if not user:
        return jsonify({"ok": False, "error": "Not logged in"}), 401

    data = request.get_json() or {}
    name = (data.get("name") or "").strip()

    if not name:
        return jsonify({"ok": False, "error": "Folder name is required"}), 400

    folder = Folder(name=name, user_id=user.id)
    db.session.add(folder)
    db.session.commit()

    return jsonify({
        "ok": True,
        "folder": {
            "id": folder.id,
            "name": folder.name,
        }
    })


@app.route("/api/library/playlists", methods=["POST"])
def api_create_playlist():
    user = get_current_user()
    if not user:
        return jsonify({"ok": False, "error": "Not logged in"}), 401

    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    folder_id = data.get("folder_id")

    if not name:
        return jsonify({"ok": False, "error": "Playlist name is required"}), 400

    folder = None
    if folder_id is not None:
        folder = Folder.query.filter_by(id=folder_id, user_id=user.id).first()
        if not folder:
            return jsonify({"ok": False, "error": "Folder not found"}), 404

    playlist = Playlist(
        name=name,
        user_id=user.id,
        folder_id=folder.id if folder else None,
    )
    db.session.add(playlist)
    db.session.commit()

    return jsonify({
        "ok": True,
        "playlist": {
            "id": playlist.id,
            "name": playlist.name,
            "folder_id": playlist.folder_id,
        }
    })

@app.route("/api/search_songs")
def api_search_songs():
    user = get_current_user()
    if not user:
        return jsonify({"ok": False, "error": "Not logged in"}), 401

    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"ok": True, "songs": []})

    results = (
        Song.query
        .filter(
            or_(
                Song.title.ilike(f"%{q}%"),
                Song.artist.ilike(f"%{q}%"),
                Song.album.ilike(f"%{q}%"),
            )
        )
        .order_by(Song.title.asc())
        .limit(8)
        .all()
    )

    songs = []
    for s in results:
        cover_url = s.cover_url or url_for(
            "static", filename="images/default_cover.jpg"
        )
        songs.append(
            {
                "id": s.id,
                "title": s.title,
                "artist": s.artist or "",
                "coverUrl": cover_url,
            }
        )

    return jsonify({"ok": True, "songs": songs})


@app.route("/api/library/playlists/<int:playlist_id>", methods=["PUT", "DELETE"])
def api_playlist_detail(playlist_id):
    user = get_current_user()
    if not user:
        return jsonify({"ok": False, "error": "Not logged in"}), 401

    playlist = Playlist.query.filter_by(id=playlist_id, user_id=user.id).first()
    if not playlist:
        return jsonify({"ok": False, "error": "Playlist not found"}), 404

    if request.method == "PUT":
        data = request.get_json() or {}
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"ok": False, "error": "Name is required"}), 400

        playlist.name = name
        db.session.commit()

        return jsonify({
            "ok": True,
            "playlist": {
                "id": playlist.id,
                "name": playlist.name,
                "folder_id": playlist.folder_id,
            },
        })

    # DELETE
    db.session.delete(playlist)
    db.session.commit()
    return jsonify({"ok": True})

@app.route("/api/library/folders/<int:folder_id>", methods=["PUT", "DELETE"])
def api_folder_detail(folder_id):
    user = get_current_user()
    if not user:
        return jsonify({"ok": False, "error": "Not logged in"}), 401

    folder = Folder.query.filter_by(id=folder_id, user_id=user.id).first()
    if not folder:
        return jsonify({"ok": False, "error": "Folder not found"}), 404

    if request.method == "PUT":
        data = request.get_json() or {}
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"ok": False, "error": "Name is required"}), 400

        folder.name = name
        db.session.commit()

        return jsonify({
            "ok": True,
            "folder": {
                "id": folder.id,
                "name": folder.name,
            },
        })

    # DELETE → sekalian hapus semua playlist di dalam folder ini
    Playlist.query.filter_by(user_id=user.id, folder_id=folder.id).delete()
    db.session.delete(folder)
    db.session.commit()
    return jsonify({"ok": True})


# ---------- HOME ----------
@app.route("/home")
def home_page():
    user = get_current_user()
    if not user:
        session.clear()
        return redirect(url_for("login"))

    root_playlists = Playlist.query.filter_by(user_id=user.id, folder_id=None).all()
    folders = Folder.query.filter_by(user_id=user.id).all()

    # rekomendasi personal berbasis playlist user (pakai hash map)
    recommended_songs = get_recommended_songs_for_user(user, limit=30)
    random_songs = Song.query.order_by(func.random()).limit(10).all()
    # ambil satu lagu rekomendasi utama (kalau mau dipakai di hero, dsb)
    rec_song = recommended_songs[0] if recommended_songs else None

    return render_template(
        "home.html",
        current_user=user,
        root_playlists=root_playlists,
        folders=folders,
        recommended_songs=recommended_songs,
        rec_song=rec_song,  
        random_songs = random_songs
    )



# ---------- PLAYLIST DETAIL ----------
@app.route("/playlist/<playlist_name>")
def playlist_page(playlist_name):
    user = get_current_user()
    if not user:
        session.clear()
        return redirect(url_for("login"))

    playlist = Playlist.query.filter_by(user_id=user.id, name=playlist_name).first()
    if not playlist:
        # kalau playlist gak ketemu
        display_name = playlist_name
        songs = []
    else:
        display_name = playlist.name
        # pakai relasi many-to-many
        songs = (
            playlist.songs
            .order_by(Song.created_at.asc())
            .all()
        )

    song_count = len(songs)

    total_duration_ms = sum(s.duration_ms or 0 for s in songs)
    total_minutes = total_duration_ms // 60000
    total_seconds = (total_duration_ms // 1000) % 60

    # Label durasi
    if song_count == 0 or total_duration_ms == 0:
        duration_label = "0 min"
    else:
        if total_minutes:
            duration_label = f"{total_minutes} min"
        else:
            duration_label = f"{total_seconds}s"

    # Tentukan cover:
    if playlist and playlist.cover_url:
    # Sudah berisi url_for("serve_cover", filename=...)
        cover_url = playlist.cover_url
    elif song_count > 0 and songs[0].cover_url:
    # Pakai cover lagu pertama (juga sudah full URL)
        cover_url = songs[0].cover_url
    else:
    # JANGAN kasih default di Python, biar template yang handle
        cover_url = None   # atau "" juga boleh


        # Rekomendasi lagu berdasarkan artist & genre di playlist ini
    if playlist:
        recommended_songs = get_recommended_songs_for_playlist(playlist, limit=15)
    else:
        recommended_songs = []


    root_playlists = Playlist.query.filter_by(user_id=user.id, folder_id=None).all()
    folders = Folder.query.filter_by(user_id=user.id).all()

    return render_template(
        "playlist.html",
        playlist_name=display_name,
        playlist=playlist,                 # <-- tambahin ini
        current_user=user,
        root_playlists=root_playlists,
        folders=folders,
        songs=songs,
        song_count=song_count,
        duration_label=duration_label,
        cover_url=cover_url,
        recommended_songs=recommended_songs,  # <-- dan ini
    )


@app.route("/playlist/<playlist_name>/remove-song/<int:song_id>", methods=["POST"])
def remove_song_from_playlist(playlist_name, song_id):
    user = get_current_user()
    if not user:
        session.clear()
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "error": "AUTH_REQUIRED"}), 401
        return redirect(url_for("login"))

    playlist = Playlist.query.filter_by(user_id=user.id, name=playlist_name).first()
    if not playlist:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "error": "PLAYLIST_NOT_FOUND"}), 404
        return redirect(url_for("home_page"))

    song = Song.query.get_or_404(song_id)

    # many-to-many, lazy="dynamic"
    if hasattr(playlist.songs, "filter_by"):
        existing = playlist.songs.filter_by(id=song_id).first()
    else:
        existing = song if song in playlist.songs else None

    removed = False
    if existing:
        playlist.songs.remove(existing)
        db.session.commit()
        removed = True

    # respon AJAX
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "success": True,
            "removed": removed,
            "song_id": song_id,
            "playlist_name": playlist.name,
        })

    # fallback redirect biasa
    next_url = request.form.get("next")
    if next_url:
        return redirect(next_url)
    return redirect(url_for("playlist_page", playlist_name=playlist.name))


    
def allowed_image_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS



@app.route("/playlist/<playlist_name>/upload-cover", methods=["POST"])
def upload_playlist_cover(playlist_name):
    user = get_current_user()
    if not user:
        session.clear()
        return redirect(url_for("login"))

    playlist = Playlist.query.filter_by(
        user_id=user.id,
        name=playlist_name
    ).first_or_404()

    file = request.files.get("cover")
    if not file or file.filename == "":
        return redirect(url_for("playlist_page", playlist_name=playlist.name))

    if not allowed_image_file(file.filename):
        return redirect(url_for("playlist_page", playlist_name=playlist.name))

    filename = secure_filename(file.filename)
    name, ext = os.path.splitext(filename)
    unique = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    filename = f"{name}_{unique}{ext}"

    cover_folder = app.config["COVER_UPLOAD_FOLDER"]
    os.makedirs(cover_folder, exist_ok=True)
    cover_path = os.path.join(cover_folder, filename)
    file.save(cover_path)

    # simpan URL yang bisa dilayani oleh /covers/<filename>
    playlist.cover_url = url_for("serve_cover", filename=filename)
    db.session.commit()

    return redirect(url_for("playlist_page", playlist_name=playlist.name))




@app.route("/song/<int:song_id>")
def song_page(song_id):
    user = get_current_user()
    if not user:
        session.clear()
        return redirect(url_for("login"))

    # ==== data buat sidebar (sama seperti di home / library) ====
    root_playlists = Playlist.query.filter_by(
        user_id=user.id,
        folder_id=None
    ).all()
    folders = Folder.query.filter_by(user_id=user.id).all()

    # ==== ambil lagu; JANGAN pakai get_or_404 supaya bisa handle custom ====
    song = Song.query.get(song_id)

    # ==== kalau lagu sudah dihapus / tidak ditemukan ====
    if song is None:
        return render_template(
            "song_removed.html",
            current_user=user,
            root_playlists=root_playlists,
            folders=folders,
            missing_song_id=song_id,
            message=(
                "Maaf, lagu yang Anda tuju sudah dihapus karena beberapa alasan "
                "atau dianggap mengganggu kebijakan kami."
            ),
        ), 404

    # ==== durasi (kalau lagu masih ada) ====
    total_seconds = (song.duration_ms or 0) // 1000
    minutes = total_seconds // 60
    seconds = total_seconds % 60

    # ==== lagu lain dari artist yang sama (More by…) ====
    more_songs = (
        Song.query
        .filter(Song.artist == song.artist, Song.id != song.id)
        .order_by(Song.created_at.desc())
        .limit(10)
        .all()
    )

    # ==== render detail lagu seperti biasa ====
    return render_template(
        "song_detail.html",
        current_user=user,
        song=song,
        minutes=minutes,
        seconds=seconds,
        more_songs=more_songs,
        root_playlists=root_playlists,
        folders=folders,
    )


@app.route("/songs")
def song_library():
    user = get_current_user()
    if not user:
        session.clear()
        return redirect(url_for("login"))

    view = request.args.get("view", "all")  # 'all' | 'history' | 'playlists'

    songs = []
    root_playlists = []
    folders = []

    if view == "all":
        songs = Song.query.order_by(Song.title.asc()).all()
    elif view == "playlists":
        root_playlists = Playlist.query.filter_by(
            user_id=user.id, folder_id=None
        ).all()
        folders = Folder.query.filter_by(user_id=user.id).all()
    # view == 'history' → data diambil dari localStorage lewat JS

    return render_template(
        "song_library.html",
        view=view,
        songs=songs,
        root_playlists=root_playlists,
        folders=folders,
        current_user=user,
    )



@app.route("/folder/<int:folder_id>")
def folder_page(folder_id):
    user = get_current_user()
    if not user:
        session.clear()
        return redirect(url_for("login"))

    # pastikan folder milik user ini
    folder = Folder.query.filter_by(id=folder_id, user_id=user.id).first()
    if not folder:
        # kalau folder nggak ada / bukan miliknya, balikin ke home
        return redirect(url_for("home_page"))

    # playlist di root & daftar folder tetap dikirim buat sidebar
    root_playlists = Playlist.query.filter_by(user_id=user.id, folder_id=None).all()
    folders = Folder.query.filter_by(user_id=user.id).all()

    # playlist khusus di folder ini
    playlists = Playlist.query.filter_by(user_id=user.id, folder_id=folder.id).all()

    return render_template(
        "folder.html",
        current_user=user,
        folder=folder,
        playlists=playlists,
        root_playlists=root_playlists,
        folders=folders,
    )


# ---------- LOGOUT ----------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ================== MAIN ==================

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        create_default_admin()
        create_default_library()
    app.run(debug=True)
