from flask import Flask, render_template, request, send_from_directory
from pytubefix import YouTube
import os
import subprocess

app = Flask(__name__)
app.config['DOWNLOAD_FOLDER'] = 'downloads'

if not os.path.exists(app.config['DOWNLOAD_FOLDER']):
    os.makedirs(app.config['DOWNLOAD_FOLDER'])

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/info', methods=['POST'])
def get_info():
    url = request.form['url']
    try:
        # Bypass the age restriction and signature verification
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
            filename = stream.default_filename
            stream.download(output_path=app.config['DOWNLOAD_FOLDER'])
            return send_from_directory(
                app.config['DOWNLOAD_FOLDER'],
                filename,
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
            
            # Download video and audio streams to temporary files
            video_path = video_stream.download(output_path=app.config['DOWNLOAD_FOLDER'], filename_prefix="video_")
            audio_path = audio_stream.download(output_path=app.config['DOWNLOAD_FOLDER'], filename_prefix="audio_")
            
            # Merge video and audio using ffmpeg
            output_filename = video_stream.default_filename
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
            
            # Remove the temporary files
            os.remove(video_path)
            os.remove(audio_path)
            
            return send_from_directory(
                app.config['DOWNLOAD_FOLDER'],
                output_filename,
                as_attachment=True
            )
        else:
            return "Error: Invalid download option."
    
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == '__main__':
    app.run(debug=True)