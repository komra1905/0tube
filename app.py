from flask import Flask, render_template, request, send_from_directory
from pytubefix import YouTube
import os
import subprocess
import re
import threading

app = Flask(__name__)
app.config['DOWNLOAD_FOLDER'] = 'downloads'

if not os.path.exists(app.config['DOWNLOAD_FOLDER']):
    os.makedirs(app.config['DOWNLOAD_FOLDER'])

def sanitize_filename(filename):
    # Windows does not allow: \ / : * ? " < > |
    return re.sub(r'[\\\/:*?"<>|]', '_', filename)

def delayed_remove_file(file_path, delay=5):
    """Remove file after a delay in seconds."""
    def remove_file():
        try:
            os.remove(file_path)
            app.logger.info(f"Removed file: {file_path}")
        except Exception as e:
            app.logger.error(f"Error removing file {file_path}: {e}")
    timer = threading.Timer(delay, remove_file)
    timer.start()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/info', methods=['POST'])
def get_info():
    url = request.form['url']
    try:
        yt = YouTube(url, use_oauth=False, allow_oauth_cache=True)
        
        video_info = {
            'title': yt.title,
            'thumbnail': yt.thumbnail_url,
            'author': yt.author,
            'length': yt.length,
            'progressive_streams': [],
            'adaptive_streams': [],
            'audio_streams': []
        }

        # Fetch progressive streams (video + audio)
        progressive_streams = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc()
        video_info['progressive_streams'] = [{
            'itag': stream.itag,
            'resolution': stream.resolution
        } for stream in progressive_streams if stream.resolution]

        # Fetch adaptive video streams (video only)
        adaptive_streams = yt.streams.filter(adaptive=True, only_video=True, file_extension='mp4').order_by('resolution').desc()
        video_info['adaptive_streams'] = [{
            'itag': stream.itag,
            'resolution': stream.resolution
        } for stream in adaptive_streams if stream.resolution]

        # Fetch audio streams
        audio_streams = yt.streams.filter(only_audio=True).order_by('abr').desc()
        video_info['audio_streams'] = [{
            'itag': stream.itag,
            'abr': stream.abr
        } for stream in audio_streams]

        return render_template('download.html', video=video_info, url=url)

    except Exception as e:
        return f"Error: {str(e)}"

@app.route('/download', methods=['POST'])
def download():
    url = request.form['url']
    option = request.form['itag']
    try:
        # Progressive download: option value starts with "progressive-"
        if option.startswith("progressive-"):
            prog_itag = option.split("progressive-")[1]
            yt = YouTube(url)
            stream = yt.streams.get_by_itag(prog_itag)
            orig_filename = stream.default_filename
            safe_filename = sanitize_filename(orig_filename)
            stream.download(output_path=app.config['DOWNLOAD_FOLDER'], filename=safe_filename)
            file_path = os.path.join(app.config['DOWNLOAD_FOLDER'], safe_filename)

            # Schedule deletion of file after 5 seconds
            delayed_remove_file(file_path)

            return send_from_directory(
                app.config['DOWNLOAD_FOLDER'],
                safe_filename,
                as_attachment=True
            )
        # Adaptive download: option value starts with "adaptive-"
        elif option.startswith("adaptive-"):
            video_itag = option.split("adaptive-")[1]
            # Expect an audio selection from the form
            audio_itag = request.form.get('audio_itag')
            if not audio_itag:
                return "Error: No audio stream selected for adaptive download."
            yt = YouTube(url)
            video_stream = yt.streams.get_by_itag(video_itag)
            audio_stream = yt.streams.get_by_itag(audio_itag)
            
            video_orig = video_stream.default_filename
            video_safe = sanitize_filename(video_orig)
            audio_orig = audio_stream.default_filename
            audio_safe = sanitize_filename(audio_orig)
            
            video_path = video_stream.download(output_path=app.config['DOWNLOAD_FOLDER'], filename="video_" + video_safe)
            audio_path = audio_stream.download(output_path=app.config['DOWNLOAD_FOLDER'], filename="audio_" + audio_safe)
            
            output_filename = video_safe  # Use sanitized filename for output
            output_path = os.path.join(app.config['DOWNLOAD_FOLDER'], output_filename)
            cmd = [
                "ffmpeg",
                "-y",                # overwrite without asking
                "-i", video_path,
                "-i", audio_path,
                "-c:v", "copy",
                "-c:a", "aac",
                output_path
            ]
            subprocess.run(cmd, check=True)
            
            # Remove the temporary video and audio files immediately
            os.remove(video_path)
            os.remove(audio_path)

            # Schedule deletion of merged output file after 5 seconds
            delayed_remove_file(output_path)

            return send_from_directory(
                app.config['DOWNLOAD_FOLDER'],
                output_filename,
                as_attachment=True
            )
        # Audio-only download (MP3) with conversion
        elif option == "mp3":
            yt = YouTube(url)
            stream = yt.streams.filter(only_audio=True).order_by('abr').desc().first()
            orig_filename = stream.default_filename
            safe_orig = sanitize_filename(orig_filename)
            audio_path = stream.download(output_path=app.config['DOWNLOAD_FOLDER'], filename=safe_orig)
            
            mp3_filename = os.path.splitext(safe_orig)[0] + ".mp3"
            mp3_path = os.path.join(app.config['DOWNLOAD_FOLDER'], mp3_filename)
            cmd = [
                "ffmpeg",
                "-y",            # Overwrite if exists
                "-i", audio_path,
                "-vn",           # No video
                "-ab", "192k",   # Audio bitrate
                "-ar", "44100",  # Sampling rate
                "-f", "mp3",
                mp3_path
            ]
            subprocess.run(cmd, check=True)
            
            os.remove(audio_path)

            # Schedule deletion of converted mp3 file after 5 seconds
            delayed_remove_file(mp3_path)

            return send_from_directory(
                app.config['DOWNLOAD_FOLDER'],
                mp3_filename,
                as_attachment=True
            )
        else:
            return "Error: Invalid download option."
    
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == '__main__':
    app.run(debug=True)
