"""
Uygulamayı başlatma noktası.

Çalıştırmak için:
    cd web
    python run.py

Sonra tarayıcıda:  http://127.0.0.1:5000
Varsayılan admin:  admin@finanspro.com  /  Admin1234
"""
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
