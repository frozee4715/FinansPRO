"""
Veri katmanı (data access layer).

Tüm veritabanı erişimi bu paket üzerinden yapılır. Uygulamanın geri kalanı
SQLite mi Firebase mi kullanıldığını BİLMEZ — yalnızca `get_repo()` ile
dönen repository nesnesinin metodlarını çağırır.

Firebase'e geçiş:
    1. firebase_repo.py içinde FirebaseRepository sınıfını yaz (aynı metodlar).
    2. config.DATA_BACKEND = "firebase" yap.
    3. Başka HİÇBİR yeri değiştirmene gerek yok.
"""
from .repository import get_repo

__all__ = ["get_repo"]
