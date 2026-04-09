from flask import Flask
from config import Config
from routes.transcription_routes import transcription_bp

def create_app():
    """Application factory function"""
    app = Flask(__name__, template_folder='views')
    
    # Load configuration
    app.config.from_object(Config)
    
    # Initialize folders
    Config.init_app()
    
    # Register blueprints
    app.register_blueprint(transcription_bp)
    
    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5000)