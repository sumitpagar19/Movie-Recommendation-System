from flask import Flask, render_template_string, request, jsonify
import pickle
import requests
import os
from werkzeug.exceptions import RequestEntityTooLarge

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Global variables to store loaded data
movies = None
similarity = None

def download_from_gdrive(file_id, destination):
    """Download file from Google Drive using direct download link"""
    try:
        # Use the direct download URL format for Google Drive
        url = f"https://drive.google.com/uc?id={file_id}&export=download"
        
        print(f"Downloading {destination} from Google Drive...")
        
        session = requests.Session()
        response = session.get(url, stream=True)
        
        # Handle the case where Google Drive asks for confirmation for large files
        if 'confirm' in response.text:
            # Extract confirmation token
            for line in response.text.split('\n'):
                if 'confirm=' in line:
                    confirm_token = line.split('confirm=')[1].split('&')[0]
                    break
            
            # Retry with confirmation token
            url = f"https://drive.google.com/uc?id={file_id}&export=download&confirm={confirm_token}"
            response = session.get(url, stream=True)
        
        if response.status_code == 200:
            with open(destination, "wb") as f:
                for chunk in response.iter_content(chunk_size=32768):
                    if chunk:
                        f.write(chunk)
            print(f"Successfully downloaded {destination}")
            return True
        else:
            print(f"Failed to download {destination}. Status code: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"Error downloading {destination}: {str(e)}")
        return False

def load_data():
    """Load pickle files on app startup"""
    global movies, similarity
    try:
        # File paths
        movie_list_path = "movie_list.pkl"
        similarity_path = "similarity.pkl"
        
        # Google Drive file IDs from your shared links
        MOVIE_LIST_GDRIVE_ID = "1oQzIf4RWUnDG43zannvii74BIYDH-aK5"  # movie_list.pkl
        SIMILARITY_GDRIVE_ID = "1kbIwDxIk6OGgNrrEJbG3Tvis3F3OTM5Q"  # similarity.pkl
        
        # Download files if they don't exist
        if not os.path.exists(movie_list_path):
            print("Downloading movie_list.pkl...")
            if not download_from_gdrive(MOVIE_LIST_GDRIVE_ID, movie_list_path):
                print("Failed to download movie_list.pkl")
                return False
        
        if not os.path.exists(similarity_path):
            print("Downloading similarity.pkl...")
            if not download_from_gdrive(SIMILARITY_GDRIVE_ID, similarity_path):
                print("Failed to download similarity.pkl")
                return False
        
        # Load the files
        print("Loading movie data...")
        with open(movie_list_path, 'rb') as f:
            movies = pickle.load(f)
        
        print("Loading similarity data...")
        with open(similarity_path, 'rb') as f:
            similarity = pickle.load(f)
        
        print(f"Loaded {len(movies)} movies successfully!")
        return True
        
    except Exception as e:
        print(f"Error loading pickle files: {e}")
        return False

def fetch_poster_and_rating(movie_id):
    """Fetch poster and rating from TMDB API"""
    try:
        TMDB_API_KEY = os.getenv("TMDB_API_KEY")
        if not TMDB_API_KEY:
            print("Warning: TMDB_API_KEY not set, using placeholder images")
            return "https://via.placeholder.com/500x750/1a1a1a/ffffff?text=No+API+Key", "N/A"

        url = f"https://api.themoviedb.org/3/movie/{movie_id}?api_key={TMDB_API_KEY}&language=en-US"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get('poster_path'):
            full_path = "https://image.tmdb.org/t/p/w500/" + data['poster_path']
        else:
            full_path = "https://via.placeholder.com/500x750/1a1a1a/ffffff?text=No+Poster"

        rating = data.get('vote_average', 'N/A')
        if rating != 'N/A':
            rating = round(float(rating), 1)
        
        return full_path, rating

    except Exception as e:
        print(f"Error fetching data for movie_id {movie_id}: {e}")
        return "https://via.placeholder.com/500x750/1a1a1a/ffffff?text=Error+Loading", "N/A"

def recommend(movie):
    """Generate movie recommendations"""
    try:
        if movies is None or similarity is None:
            return [], [], []
            
        # Find movies that match the search query
        movie_matches = movies[movies['title'].str.contains(movie, case=False, na=False)]
        if movie_matches.empty:
            return [], [], []

        index = movie_matches.index[0]
        distances = sorted(list(enumerate(similarity[index])), reverse=True, key=lambda x: x[1])

        recommended_movie_names = []
        recommended_movie_posters = []
        recommended_movie_ratings = []

        # Get top 5 similar movies (excluding the input movie itself)
        for i in distances[1:6]:
            movie_id = movies.iloc[i[0]].movie_id
            poster, rating = fetch_poster_and_rating(movie_id)
            recommended_movie_posters.append(poster)
            recommended_movie_names.append(movies.iloc[i[0]].title)
            recommended_movie_ratings.append(rating)

        return recommended_movie_names, recommended_movie_posters, recommended_movie_ratings
    except Exception as e:
        print(f"Error in recommend function: {e}")
        return [], [], []

@app.route('/')
def index():
    if movies is None:
        return render_template_string(ERROR_TEMPLATE, error="Movie data not loaded. Please check server logs for details.")
    return render_template_string(INDEX_TEMPLATE)

@app.route('/api/movies')
def get_movies():
    if movies is None:
        return jsonify({'error': 'Movie data not loaded'}), 500

    query = request.args.get('q', '').lower()
    if query:
        filtered_movies = movies[movies['title'].str.contains(query, case=False, na=False)]['title'].tolist()
        return jsonify(filtered_movies[:20])
    else:
        return jsonify(movies['title'].tolist()[:50])

@app.route('/api/recommend', methods=['POST'])
def get_recommendations():
    if movies is None or similarity is None:
        return jsonify({'error': 'Movie data not loaded'}), 500

    data = request.get_json()
    movie_name = data.get('movie', '')

    if not movie_name:
        return jsonify({'error': 'Movie name is required'}), 400

    names, posters, ratings = recommend(movie_name)

    recommendations = []
    for i in range(len(names)):
        recommendations.append({
            'title': names[i],
            'poster': posters[i],
            'rating': ratings[i]
        })

    return jsonify({
        'selected_movie': movie_name,
        'recommendations': recommendations
    })

@app.route('/health')
def health_check():
    """Health check endpoint for Render"""
    status = {
        'status': 'healthy',
        'movies_loaded': movies is not None,
        'similarity_loaded': similarity is not None
    }
    if movies is not None:
        status['total_movies'] = len(movies)
    
    return jsonify(status)

# Template strings
INDEX_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🎬 CineAI - Movie Recommendation System</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700;800&display=swap');
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Poppins', sans-serif;
            background: #0a0a0a;
            color: #ffffff;
            min-height: 100vh;
            overflow-x: hidden;
            position: relative;
        }
        body::before {
            content: '';
            position: fixed;
            top: 0; left: 0; width: 100%; height: 100%;
            background: radial-gradient(circle at 20% 80%, rgba(120, 0, 255, 0.1) 0%, transparent 50%),
                        radial-gradient(circle at 80% 20%, rgba(0, 255, 255, 0.1) 0%, transparent 50%),
                        radial-gradient(circle at 40% 40%, rgba(255, 0, 150, 0.08) 0%, transparent 50%);
            z-index: -1;
            animation: backgroundShift 20s ease-in-out infinite;
        }
        @keyframes backgroundShift { 0%, 100% { opacity: 1; } 50% { opacity: 0.7; } }
        .container { max-width: 1400px; margin: 0 auto; padding: 40px 20px; position: relative; z-index: 1; }
        .header { text-align: center; margin-bottom: 80px; }
        .header h1 {
            font-size: 4.5rem; font-weight: 700;
            background: linear-gradient(135deg, #e8e8e8 0%, #ffffff 50%, #f0f0f0 100%);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
            margin-bottom: 20px; letter-spacing: -1px;
        }
        .header p { color: #a0a0a0; font-size: 1.4rem; font-weight: 300; max-width: 600px; margin: 0 auto; line-height: 1.6; }
        .search-section { margin-bottom: 80px; position: relative; }
        .search-container { max-width: 800px; margin: 0 auto; position: relative; }
        .search-wrapper {
            background: linear-gradient(135deg, rgba(255, 255, 255, 0.05) 0%, rgba(0, 0, 0, 0.3) 100%);
            border-radius: 30px; padding: 8px; border: 1px solid rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(20px); box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.1);
            position: relative; overflow: hidden;
        }
        .search-input {
            width: 100%; padding: 25px 30px; font-size: 1.3rem; border: none; border-radius: 25px; outline: none;
            background: rgba(0, 0, 0, 0.3); color: #ffffff; font-family: 'Poppins', sans-serif; font-weight: 400;
            transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
        }
        .search-input::placeholder { color: #666; }
        .search-input:focus {
            background: rgba(0, 0, 0, 0.5);
            box-shadow: 0 0 0 2px rgba(0, 255, 255, 0.4), 0 0 40px rgba(0, 255, 255, 0.2), inset 0 0 20px rgba(0, 255, 255, 0.05);
            transform: scale(1.02);
        }
        .dropdown {
            position: absolute; top: 100%; left: 8px; right: 8px; background: rgba(0, 0, 0, 0.9);
            border: 1px solid rgba(0, 255, 255, 0.2); border-radius: 20px; max-height: 300px; overflow-y: auto;
            z-index: 1000; display: none; backdrop-filter: blur(20px); margin-top: 10px; box-shadow: 0 20px 40px rgba(0, 0, 0, 0.6);
        }
        .dropdown-item {
            padding: 18px 25px; cursor: pointer; border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            transition: all 0.3s ease; color: #ccc; font-weight: 400;
        }
        .dropdown-item:hover {
            background: rgba(255, 255, 255, 0.08); color: #ffffff; transform: translateX(8px);
            border-left: 2px solid rgba(255, 255, 255, 0.3);
        }
        .dropdown-item:last-child { border-bottom: none; }
        .recommend-btn {
            display: block; margin: 40px auto 0; padding: 18px 48px; font-size: 1.1rem; font-weight: 500;
            background: rgba(255, 255, 255, 0.08); color: #ffffff; border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 12px; cursor: pointer; transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            font-family: 'Poppins', sans-serif; backdrop-filter: blur(10px); position: relative; overflow: hidden;
        }
        .recommend-btn:hover {
            background: rgba(255, 255, 255, 0.12); border-color: rgba(255, 255, 255, 0.3); transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(0, 0, 0, 0.3), 0 0 0 1px rgba(255, 255, 255, 0.1);
        }
        .recommend-btn:disabled { opacity: 0.7; cursor: not-allowed; transform: none; }
        .selected-movie {
            background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.15); padding: 30px;
            border-radius: 16px; margin: 40px 0; text-align: center; display: none; backdrop-filter: blur(20px);
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
        }
        .selected-movie h3 { color: rgba(255, 255, 255, 0.7); margin-bottom: 15px; font-weight: 500; font-size: 1.2rem; }
        .selected-movie p { color: #ffffff; font-size: 1.2rem; font-weight: 500; }
        .recommendations { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 40px; margin-top: 80px; }
        .movie-card {
            background: linear-gradient(145deg, rgba(255, 255, 255, 0.03), rgba(0, 0, 0, 0.3));
            border-radius: 25px; padding: 25px; text-align: center; border: 1px solid rgba(255, 255, 255, 0.05);
            transition: all 0.5s cubic-bezier(0.4, 0, 0.2, 1); position: relative; overflow: hidden; backdrop-filter: blur(10px);
        }
        .movie-card:hover { transform: translateY(-8px); box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4), 0 0 0 1px rgba(255, 255, 255, 0.1); }
        .movie-poster { width: 100%; height: 350px; object-fit: cover; border-radius: 20px; margin-bottom: 25px; transition: all 0.5s ease; box-shadow: 0 15px 35px rgba(0, 0, 0, 0.4); }
        .movie-card:hover .movie-poster { transform: scale(1.02); box-shadow: 0 15px 35px rgba(0, 0, 0, 0.5); }
        .movie-title { font-size: 1.3rem; font-weight: 600; color: #ffffff; margin-bottom: 15px; line-height: 1.4; min-height: 60px; display: flex; align-items: center; justify-content: center; }
        .movie-rating { display: flex; align-items: center; justify-content: center; gap: 10px; font-size: 1.2rem; font-weight: 600; }
        .rating-star { color: #ffd700; }
        .rating-value { color: rgba(255, 255, 255, 0.9); }
        .loading { text-align: center; padding: 80px; display: none; }
        .spinner { width: 40px; height: 40px; border: 3px solid rgba(255, 255, 255, 0.1); border-top: 3px solid rgba(255, 255, 255, 0.6); border-radius: 50%; animation: spin 1s linear infinite; margin: 0 auto 30px; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        .loading p { font-size: 1.4rem; color: #a0a0a0; font-weight: 500; }
        .error-message { background: rgba(220, 38, 38, 0.1); border: 1px solid rgba(220, 38, 38, 0.3); color: #fca5a5; padding: 20px; border-radius: 12px; text-align: center; margin: 30px 0; display: none; backdrop-filter: blur(20px); font-weight: 400; }
        @media (max-width: 768px) { .header h1 { font-size: 3rem; } .header p { font-size: 1.1rem; } .search-input { padding: 20px 25px; font-size: 1.1rem; } .recommendations { grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 30px; } .movie-poster { height: 300px; } }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>CineAI</h1>
            <p>Discover your next cinematic adventure with AI-powered recommendations tailored just for you</p>
        </div>
        <div class="search-section">
            <div class="search-container">
                <div class="search-wrapper">
                    <input type="text" id="movieSearch" class="search-input" placeholder="Search for your favorite movie..." autocomplete="off">
                </div>
                <div id="dropdown" class="dropdown"></div>
            </div>
            <button id="recommendBtn" class="recommend-btn">Get Recommendations</button>
        </div>
        <div id="selectedMovie" class="selected-movie">
            <h3>Selected Movie:</h3>
            <p id="selectedMovieTitle"></p>
        </div>
        <div id="errorMessage" class="error-message"></div>
        <div id="loading" class="loading">
            <div class="spinner"></div>
            <p>Analyzing your preferences and finding perfect matches...</p>
        </div>
        <div id="recommendations" class="recommendations"></div>
    </div>
    <script>
        let allMovies = []; let selectedMovie = '';
        async function loadMovies() { try { const response = await fetch('/api/movies'); allMovies = await response.json(); console.log('Movies loaded successfully'); } catch (error) { showError('Failed to load movie database'); console.error('Error loading movies:', error); } }
        const searchInput = document.getElementById('movieSearch'); const dropdown = document.getElementById('dropdown');
        searchInput.addEventListener('input', function() { const query = this.value.toLowerCase().trim(); if (query.length === 0) { dropdown.style.display = 'none'; return; } const filtered = allMovies.filter(movie => movie.toLowerCase().includes(query)).slice(0, 12); if (filtered.length > 0) { dropdown.innerHTML = filtered.map(movie => `<div class="dropdown-item" onclick="selectMovie('${movie.replace(/'/g, "\\\'")}')"> ${movie} </div>`).join(''); dropdown.style.display = 'block'; } else { dropdown.innerHTML = '<div class="dropdown-item" style="color: #666; cursor: default;">No movies found</div>'; dropdown.style.display = 'block'; } });
        document.addEventListener('click', function(event) { if (!searchInput.contains(event.target) && !dropdown.contains(event.target)) { dropdown.style.display = 'none'; } });
        function selectMovie(movie) { selectedMovie = movie; searchInput.value = movie; dropdown.style.display = 'none'; const selectedDiv = document.getElementById('selectedMovie'); document.getElementById('selectedMovieTitle').textContent = movie; selectedDiv.style.display = 'block'; }
        document.getElementById('recommendBtn').addEventListener('click', async function() { const movieToRecommend = selectedMovie || searchInput.value.trim(); if (!movieToRecommend) { showError('Please select a movie first to get personalized recommendations'); return; } await getRecommendations(movieToRecommend); });
        async function getRecommendations(movie) { const loading = document.getElementById('loading'); const recommendations = document.getElementById('recommendations'); const recommendBtn = document.getElementById('recommendBtn'); loading.style.display = 'block'; recommendations.innerHTML = ''; recommendBtn.disabled = true; recommendBtn.textContent = 'Analyzing Your Taste...'; hideError(); try { const response = await fetch('/api/recommend', { method: 'POST', headers: { 'Content-Type': 'application/json', }, body: JSON.stringify({ movie: movie }) }); const data = await response.json(); if (data.error) { throw new Error(data.error); } loading.style.display = 'none'; if (data.recommendations && data.recommendations.length > 0) { recommendations.innerHTML = data.recommendations.map((movie) => `<div class="movie-card"> <img src="${movie.poster}" alt="${movie.title}" class="movie-poster" onerror="this.src='https://via.placeholder.com/500x750/1a1a1a/ffffff?text=${encodeURIComponent(movie.title)}'"> <div class="movie-title">${movie.title}</div> <div class="movie-rating"> <span class="rating-star">⭐</span> <span class="rating-value">${movie.rating}/10</span> </div> </div>`).join(''); } else { recommendations.innerHTML = `<div style="text-align: center; color: #666; grid-column: 1/-1; padding: 60px;"> <div style="font-size: 4rem; margin-bottom: 20px;">🤔</div> <h3 style="color: #fff; margin-bottom: 10px;">No recommendations found</h3> <p>Try searching for a different movie or check the spelling!</p> </div>`; } } catch (error) { loading.style.display = 'none'; showError('Failed to get recommendations: ' + error.message); console.error('Recommendation error:', error); } finally { recommendBtn.disabled = false; recommendBtn.innerHTML = 'Get Recommendations'; } }
        function showError(message) { const errorDiv = document.getElementById('errorMessage'); errorDiv.innerHTML = message; errorDiv.style.display = 'block'; }
        function hideError() { document.getElementById('errorMessage').style.display = 'none'; }
        loadMovies();
    </script>
</body>
</html>'''

ERROR_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Error - CineAI</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700&display=swap');
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Poppins', sans-serif; background: #0a0a0a; color: #ffffff; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; }
        .error-container { background: linear-gradient(145deg, rgba(255, 255, 255, 0.05), rgba(0, 0, 0, 0.3)); padding: 60px 50px; border-radius: 30px; text-align: center; box-shadow: 0 30px 60px rgba(0, 0, 0, 0.5); backdrop-filter: blur(20px); border: 1px solid rgba(255, 255, 255, 0.1); max-width: 600px; }
        .error-icon { font-size: 5rem; margin-bottom: 30px; }
        h1 { color: #ff0064; margin-bottom: 25px; font-size: 2.5rem; font-weight: 700; }
        p { color: #a0a0a0; line-height: 1.8; margin-bottom: 20px; font-size: 1.1rem; }
        .error-details { background: rgba(255, 0, 100, 0.1); border: 1px solid rgba(255, 0, 100, 0.3); padding: 25px; border-radius: 15px; margin: 30px 0; color: #ff6b9d; }
    </style>
</head>
<body>
    <div class="error-container">
        <div class="error-icon">⚠️</div>
        <h1>System Error</h1>
        <div class="error-details">
            <p><strong>{{ error }}</strong></p>
        </div>
        <p>Please check your configuration and try again.</p>
    </div>
</body>
</html>'''

def render_template_string(template, **context):
    """Simple template renderer for basic variable substitution"""
    for key, value in context.items():
        template = template.replace('{{ ' + key + ' }}', str(value))
    return template

if __name__ == '__main__':
    print("Starting CineAI Movie Recommendation System...")
    
    # Load data on startup
    if not load_data():
        print("Warning: Failed to load data. App will start but functionality will be limited.")
    else:
        print("Data loaded successfully! App is ready.")
    
    # Get port from environment or default to 5000
    port = int(os.environ.get('PORT', 5000))
    
    # Run the app
    app.run(host='0.0.0.0', port=port, debug=False)