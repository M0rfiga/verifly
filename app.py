"""Ponto de entrada do servidor: python app.py ou gunicorn app:app."""

from python_modules.web import app


if __name__ == "__main__":
    app.run(debug=True)
